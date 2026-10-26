"""
Antigravity Mobile Remote Controller
====================================
A lightweight, mobile-first web interface to control Antigravity AI sessions,
run shell commands, stream responses in real-time, and access your workstation
from any phone over Wi-Fi, Tailscale, or 4G/5G Cellular (via Cloudflare Tunnel).

Zero external dependencies required (Pure Python 3 standard library).
"""

import os
import sys
import json
import glob
import time
import socket
import re
import secrets
import urllib.parse
import urllib.request
import subprocess
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import base64
import uuid
import shutil

PORT = int(os.environ.get("PORT", 8080))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)
HOME_DIR = os.path.expanduser("~")
PIN_FILE = os.path.join(BASE_DIR, "pin.txt")

# Dynamic discovery of Antigravity paths
BRAIN_DIR = os.environ.get("ANTIGRAVITY_BRAIN", os.path.join(HOME_DIR, ".gemini", "antigravity", "brain"))
WORKSPACE_DIR = os.getcwd()

def save_uploaded_image(data_url):
    try:
        if "," in data_url:
            header, b64_data = data_url.split(",", 1)
        else:
            header = ""
            b64_data = data_url
        ext = ".jpg"
        if "image/png" in header:
            ext = ".png"
        elif "image/webp" in header:
            ext = ".webp"
        elif "image/gif" in header:
            ext = ".gif"
        fname = f"photo_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
        fpath = os.path.join(UPLOADS_DIR, fname)
        with open(fpath, "wb") as f:
            f.write(base64.b64decode(b64_data))
        return fname, fpath
    except Exception as e:
        print(f"Error saving image: {e}")
        return None, None

def list_workspace_html_files():
    html_files = []
    try:
        for root, dirs, files in os.walk(WORKSPACE_DIR):
            dirs[:] = [d for d in dirs if d not in [".git", ".gemini", "node_modules", ".venv", "__pycache__", ".vscode"]]
            for f in files:
                if f.lower().endswith((".html", ".htm")):
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, WORKSPACE_DIR)
                    html_files.append({
                        "path": rel.replace("\\", "/"),
                        "name": f,
                        "mtime": os.path.getmtime(full)
                    })
    except Exception:
        pass
    html_files.sort(key=lambda x: x["mtime"], reverse=True)
    return html_files

# Detect agentapi executable
if sys.platform == "win32":
    CLOUDFLARED_NAME = "cloudflared.exe"
    DEFAULT_AGENTAPI = os.path.join(HOME_DIR, ".gemini", "antigravity", "bin", "agentapi.bat")
else:
    CLOUDFLARED_NAME = "cloudflared"
    DEFAULT_AGENTAPI = os.path.join(HOME_DIR, ".gemini", "antigravity", "bin", "agentapi")

AGENTAPI_BIN = os.environ.get("AGENTAPI_BIN", DEFAULT_AGENTAPI)
CLOUDFLARED_EXE = os.path.join(BASE_DIR, CLOUDFLARED_NAME)

PUBLIC_TUNNEL_URL = None
TUNNEL_PROCESS = None
VALID_TOKENS = set()

def get_configured_pin():
    if os.path.isfile(PIN_FILE):
        try:
            with open(PIN_FILE, "r", encoding="utf-8") as f:
                pin = f.read().strip()
                if pin:
                    return pin
        except Exception:
            pass
    return os.environ.get("REMOTE_PIN", "1234")

def get_latest_conversation_id():
    if not os.path.exists(BRAIN_DIR):
        return ""
    best_id = ""
    best_mtime = 0
    try:
        for cid in os.listdir(BRAIN_DIR):
            cpath = os.path.join(BRAIN_DIR, cid, ".system_generated", "logs", "transcript.jsonl")
            if os.path.isfile(cpath):
                m = os.path.getmtime(cpath)
                if m > best_mtime:
                    best_mtime = m
                    best_id = cid
    except Exception:
        pass
    return best_id

ACTIVE_CONVERSATION_ID = get_latest_conversation_id()

def get_network_ips():
    ips = []
    # 1. Add Public Internet URL if active
    if PUBLIC_TUNNEL_URL:
        ips.append({
            "type": "🌐 Cellular / 5G / Internet",
            "ip": "Public Cloudflare Tunnel",
            "url": PUBLIC_TUNNEL_URL
        })

    # 2. Add Tailscale / Local Wi-Fi
    try:
        host = socket.gethostname()
        candidates = socket.gethostbyname_ex(host)[2]
        for ip in candidates:
            if ip.startswith("100."):
                ips.append({"type": "🔒 Tailscale VPN (Remote)", "ip": ip, "url": f"http://{ip}:{PORT}"})
            elif ip.startswith("192.168.") and not ip.startswith("192.168.220.") and not ip.startswith("192.168.128."):
                ips.append({"type": "📶 Local Wi-Fi", "ip": ip, "url": f"http://{ip}:{PORT}"})
    except Exception:
        pass

    ips.append({"type": "💻 Localhost", "ip": "127.0.0.1", "url": f"http://127.0.0.1:{PORT}"})
    return ips

def ensure_cloudflared_binary():
    if os.path.isfile(CLOUDFLARED_EXE):
        return True

    print("  [*] cloudflared binary not found. Downloading for automatic remote tunnel...")
    url = None
    if sys.platform == "win32":
        url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    elif sys.platform == "darwin":
        import platform
        arch = "arm64" if platform.machine() == "arm64" else "amd64"
        url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-{arch}"
    elif sys.platform.startswith("linux"):
        url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"

    if not url:
        return False

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(CLOUDFLARED_EXE, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        if sys.platform != "win32":
            os.chmod(CLOUDFLARED_EXE, 0o755)
        print("  [+] cloudflared downloaded successfully.")
        return True
    except Exception as e:
        print(f"  [!] Failed to auto-download cloudflared: {e}")
        return False

def start_cloudflared_tunnel():
    global PUBLIC_TUNNEL_URL, TUNNEL_PROCESS
    if not ensure_cloudflared_binary():
        print("  [!] cloudflared not available. Public internet tunnel skipped.")
        return

    cmd = [CLOUDFLARED_EXE, "tunnel", "--url", f"http://127.0.0.1:{PORT}"]
    try:
        TUNNEL_PROCESS = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
    except Exception as e:
        print(f"  [!] Failed to start cloudflared: {e}")
        return

    print("  [*] Connecting to Cloudflare global network...")

    def monitor_tunnel():
        global PUBLIC_TUNNEL_URL
        for line in iter(TUNNEL_PROCESS.stdout.readline, ''):
            if not line:
                break
            m = re.search(r'https://[a-zA-Z0-9\-]+\.trycloudflare\.com', line)
            if m:
                PUBLIC_TUNNEL_URL = m.group(0)
                print("\n" + "=" * 65)
                print("  🌐 PUBLIC INTERNET TUNNEL READY (NO WI-FI NEEDED):")
                print(f"  👉 {PUBLIC_TUNNEL_URL}")
                print(f"  🔐 Security PIN : {get_configured_pin()}")
                print("=" * 65 + "\n")

                try:
                    with open(os.path.join(BASE_DIR, "tunnel_url.txt"), "w") as tf:
                        tf.write(PUBLIC_TUNNEL_URL)
                except Exception:
                    pass

                try:
                    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(PUBLIC_TUNNEL_URL)}"
                    qr_path = os.path.join(BASE_DIR, "qr_internet.png")
                    urllib.request.urlretrieve(qr_url, qr_path)
                except Exception as ex:
                    print(f"  [!] QR download notice: {ex}")

    t = threading.Thread(target=monitor_tunnel, daemon=True)
    t.start()

def list_conversations():
    convs = []
    if not os.path.exists(BRAIN_DIR):
        return convs
    active_id = get_latest_conversation_id()
    for cid in os.listdir(BRAIN_DIR):
        cpath = os.path.join(BRAIN_DIR, cid, ".system_generated", "logs", "transcript.jsonl")
        if os.path.isfile(cpath):
            mtime = os.path.getmtime(cpath)
            title = cid[:8]
            try:
                with open(cpath, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.strip():
                            obj = json.loads(line)
                            if obj.get("type") == "USER_INPUT":
                                txt = obj.get("content", "")
                                if "<USER_REQUEST>" in txt:
                                    txt = txt.split("<USER_REQUEST>")[1].split("</USER_REQUEST>")[0]
                                title = txt.strip().replace("\n", " ")[:70]
                                break
            except Exception:
                pass
            convs.append({
                "id": cid,
                "title": title,
                "mtime": mtime,
                "is_current": (cid == active_id)
            })
    convs.sort(key=lambda x: (x["is_current"], x["mtime"]), reverse=True)
    return convs

def get_transcript(conv_id, since_index=0):
    cpath = os.path.join(BRAIN_DIR, conv_id, ".system_generated", "logs", "transcript.jsonl")
    if not os.path.isfile(cpath):
        return {"error": "Conversation not found", "steps": []}

    steps = []
    try:
        with open(cpath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    idx = obj.get("step_index", 0)
                    if idx >= since_index:
                        steps.append(obj)
                except Exception:
                    continue
    except Exception as e:
        return {"error": str(e), "steps": []}

    messages = []
    for s in steps:
        stype = s.get("type")
        idx = s.get("step_index")
        tstamp = s.get("created_at")

        if stype == "USER_INPUT":
            cnt = s.get("content", "")
            if "<USER_REQUEST>" in cnt:
                cnt = cnt.split("<USER_REQUEST>")[1].split("</USER_REQUEST>")[0].strip()
            elif "<SYSTEM_MESSAGE>" in cnt:
                cnt = cnt.strip()
            messages.append({
                "index": idx,
                "sender": "user",
                "text": cnt,
                "time": tstamp
            })

        elif stype == "SYSTEM_MESSAGE":
            cnt = s.get("content", "")
            m = re.search(r'\[Message\].*?content=(.*?)(?:\n</SYSTEM_MESSAGE>|\Z)', cnt, re.DOTALL)
            if m:
                extracted = m.group(1).strip()
                if not extracted.startswith("Task id ") and not extracted.startswith("Tool execution was"):
                    messages.append({
                        "index": idx,
                        "sender": "user",
                        "text": extracted,
                        "time": tstamp
                    })

        elif stype == "PLANNER_RESPONSE":
            content = s.get("content", "")
            tool_calls = s.get("tool_calls", [])
            thinking = s.get("thinking", "")
            status = s.get("status", "DONE")

            tcalls = []
            for tc in tool_calls:
                name = tc.get("name", "tool")
                args = tc.get("args", {})
                tcalls.append({"name": name, "args": args, "result": None, "status": "running"})

            messages.append({
                "index": idx,
                "sender": "agent",
                "text": content,
                "tool_calls": tcalls,
                "thinking": thinking,
                "status": status,
                "time": tstamp
            })

        elif stype == "GENERIC":
            res_text = s.get("content", "")
            attached = False
            for prev in reversed(messages):
                if prev.get("sender") == "agent" and prev.get("tool_calls"):
                    for tc in reversed(prev["tool_calls"]):
                        if tc.get("result") is None:
                            tc["result"] = res_text
                            tc["status"] = s.get("status", "DONE")
                            attached = True
                            break
                    if attached:
                        break
            if not attached:
                messages.append({
                    "index": idx,
                    "sender": "system",
                    "text": res_text,
                    "time": tstamp
                })

    return {"steps": messages, "total_raw_steps": len(steps)}

def get_limit_metrics():
    import glob
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    t_5h = now - timedelta(hours=5)
    t_24h = now - timedelta(hours=24)
    t_7d = now - timedelta(days=7)

    req_5h_ts = []
    in_5h = 0
    out_5h = 0
    cache_5h = 0

    req_24h_count = 0
    in_24h = 0
    out_24h = 0

    req_7d_count = 0
    in_7d = 0
    out_7d = 0
    cache_7d = 0

    # Scan transcripts across all conversations
    for cpath in glob.glob(os.path.join(BRAIN_DIR, "*", ".system_generated", "logs", "transcript.jsonl")):
        try:
            with open(cpath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    if obj.get("type") == "PLANNER_RESPONSE":
                        ts_str = obj.get("created_at")
                        if not ts_str:
                            continue
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        except Exception:
                            continue

                        inp = obj.get("input_tokens", 0)
                        out = obj.get("output_tokens", 0)
                        cache = obj.get("cache_read_tokens", 0)

                        if ts >= t_7d:
                            req_7d_count += 1
                            in_7d += inp
                            out_7d += out
                            cache_7d += cache

                        if ts >= t_24h:
                            req_24h_count += 1
                            in_24h += inp
                            out_24h += out

                        if ts >= t_5h:
                            req_5h_ts.append(ts)
                            in_5h += inp
                            out_5h += out
                            cache_5h += cache
        except Exception:
            pass

    # 5-Hour rolling window (Threshold: 250 requests)
    limit_5h_req = 250
    used_5h_req = len(req_5h_ts)
    left_5h_req = max(0, limit_5h_req - used_5h_req)
    pct_5h_req = min(100.0, round((used_5h_req / limit_5h_req) * 100, 1))

    resets_5h_str = "Rolling window"
    if req_5h_ts:
        oldest_5h = min(req_5h_ts)
        roll_off = oldest_5h + timedelta(hours=5)
        rem_secs = max(0, int((roll_off - now).total_seconds()))
        hrs = rem_secs // 3600
        mins = (rem_secs % 3600) // 60
        resets_5h_str = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"

    # Weekly rolling window (Threshold: 1,500 requests)
    limit_7d_req = 1500
    used_7d_req = req_7d_count
    left_7d_req = max(0, limit_7d_req - used_7d_req)
    pct_7d_req = min(100.0, round((used_7d_req / limit_7d_req) * 100, 1))

    # Active conversation metrics
    cid = get_latest_conversation_id()
    cpath = os.path.join(BRAIN_DIR, cid, ".system_generated", "logs", "transcript.jsonl") if cid else ""
    session_in = 0
    session_out = 0
    session_cache = 0
    last_input_tokens = 0
    steps_count = 0

    if cpath and os.path.isfile(cpath):
        try:
            with open(cpath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.strip():
                        obj = json.loads(line)
                        if obj.get("type") == "PLANNER_RESPONSE":
                            steps_count += 1
                            inp = obj.get("input_tokens", 0)
                            out = obj.get("output_tokens", 0)
                            cache = obj.get("cache_read_tokens", 0)
                            session_in += inp
                            session_out += out
                            session_cache += cache
                            if inp > 0:
                                last_input_tokens = inp
        except Exception:
            pass

    context_max = 1048576  # 1M context limit for Gemini 3.8 Flash
    context_left = max(0, context_max - last_input_tokens)
    context_pct = round((last_input_tokens / context_max) * 100, 2)

    ram_used_gb = 0
    ram_total_gb = 0
    ram_pct = 0
    try:
        ps_cmd = "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize, FreePhysicalMemory | ConvertTo-Json"
        res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=5)
        mem = json.loads(res.stdout)
        total_mb = mem["TotalVisibleMemorySize"] // 1024
        free_mb = mem["FreePhysicalMemory"] // 1024
        used_mb = total_mb - free_mb
        ram_used_gb = round(used_mb / 1024, 1)
        ram_total_gb = round(total_mb / 1024, 1)
        ram_pct = round((used_mb / total_mb) * 100, 1)
    except Exception:
        pass

    disks = []
    for d in ["C:\\", "D:\\"]:
        drive_letter = d[0] + ":"
        if os.path.exists(d):
            try:
                tot, used, free = shutil.disk_usage(d)
                disks.append({
                    "drive": drive_letter,
                    "used_gb": round(used / 2**30, 1),
                    "total_gb": round(tot / 2**30, 1),
                    "free_gb": round(free / 2**30, 1),
                    "used_pct": round((used / tot) * 100, 1)
                })
            except Exception:
                pass

    return {
        "model": "Gemini 3.8 Flash (High)",
        "active_conversation_id": cid,
        "rolling_5h": {
            "used_requests": used_5h_req,
            "limit_requests": limit_5h_req,
            "left_requests": left_5h_req,
            "used_pct": f"{pct_5h_req}%",
            "resets_in": resets_5h_str,
            "input_tokens": in_5h,
            "output_tokens": out_5h,
            "cache_tokens": cache_5h,
            "total_tokens": in_5h + out_5h
        },
        "rolling_week": {
            "used_requests": used_7d_req,
            "limit_requests": limit_7d_req,
            "left_requests": left_7d_req,
            "used_pct": f"{pct_7d_req}%",
            "input_tokens": in_7d,
            "output_tokens": out_7d,
            "cache_tokens": cache_7d,
            "total_tokens": in_7d + out_7d
        },
        "context_tokens": last_input_tokens,
        "context_limit": context_max,
        "context_left_tokens": context_left,
        "context_used_pct": f"{context_pct}%",
        "session_input_tokens": session_in,
        "session_output_tokens": session_out,
        "session_cache_read_tokens": session_cache,
        "session_total_tokens": session_in + session_out,
        "session_steps": steps_count,
        "ram": {
            "used_gb": ram_used_gb,
            "total_gb": ram_total_gb,
            "pct": f"{ram_pct}%"
        },
        "disks": disks
    }

class RemoteHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def check_auth(self):
        token = self.headers.get("X-Auth-Token")
        if not token:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            token = query.get("token", [""])[0]
        return token in VALID_TOKENS

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Auth-Token")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Auth-Token")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # Public static assets
        if path == "/" or path == "/index.html":
            file_path = os.path.join(WEB_DIR, "index.html")
            self.serve_file(file_path, "text/html; charset=utf-8")

        elif path.startswith("/web/"):
            rel = path[5:].lstrip("/\\")
            file_path = os.path.join(WEB_DIR, rel)
            if os.path.isfile(file_path):
                ext = os.path.splitext(file_path)[1].lower()
                ctype = {
                    ".html": "text/html; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".js": "application/javascript; charset=utf-8",
                    ".json": "application/json; charset=utf-8",
                    ".png": "image/png",
                    ".svg": "image/svg+xml",
                    ".ico": "image/x-icon"
                }.get(ext, "application/octet-stream")
                self.serve_file(file_path, ctype)
            else:
                self.send_error(404, "File Not Found")

        elif path.startswith("/uploads/"):
            fname = os.path.basename(path)
            file_path = os.path.join(UPLOADS_DIR, fname)
            if os.path.isfile(file_path):
                ext = os.path.splitext(file_path)[1].lower()
                ctype = {
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".png": "image/png",
                    ".webp": "image/webp",
                    ".gif": "image/gif"
                }.get(ext, "application/octet-stream")
                self.serve_file(file_path, ctype)
            else:
                self.send_error(404, "Upload Not Found")

        elif path == "/preview_file":
            rel_path = query.get("path", [""])[0]
            if not rel_path:
                self.send_error(400, "Missing path parameter")
                return
            target_path = os.path.abspath(os.path.join(WORKSPACE_DIR, rel_path))
            try:
                common = os.path.commonpath([target_path, os.path.abspath(WORKSPACE_DIR)])
                if common != os.path.abspath(WORKSPACE_DIR) or not os.path.isfile(target_path):
                    self.send_error(404, "File Not Found or Access Denied")
                    return
            except Exception:
                self.send_error(403, "Forbidden")
                return

            ext = os.path.splitext(target_path)[1].lower()
            ctype = {
                ".html": "text/html; charset=utf-8",
                ".htm": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".svg": "image/svg+xml"
            }.get(ext, "text/plain; charset=utf-8")
            self.serve_file(target_path, ctype)

        elif path == "/api/qr":
            target_url = query.get("url", [""])[0]
            if not target_url:
                target_url = PUBLIC_TUNNEL_URL or f"http://127.0.0.1:{PORT}"
            api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={urllib.parse.quote(target_url)}"
            self.send_response(302)
            self.send_header("Location", api_url)
            self.end_headers()

        # Protected endpoints below require PIN authentication
        elif path in ["/api/status", "/api/conversations", "/api/transcript", "/api/limits", "/api/html_files"]:
            if not self.check_auth():
                self.send_json({"error": "Unauthorized. PIN required.", "auth_required": True}, code=401)
                return

            if path == "/api/status":
                ips = get_network_ips()
                active_id = get_latest_conversation_id()
                self.send_json({
                    "status": "online",
                    "active_conversation_id": active_id,
                    "public_url": PUBLIC_TUNNEL_URL,
                    "ips": ips,
                    "workspace": WORKSPACE_DIR,
                    "server_time": time.strftime("%Y-%m-%d %H:%M:%S")
                })

            elif path == "/api/limits":
                data = get_limit_metrics()
                self.send_json(data)

            elif path == "/api/conversations":
                convs = list_conversations()
                active_id = get_latest_conversation_id()
                self.send_json({"conversations": convs, "active_id": active_id})

            elif path == "/api/html_files":
                files = list_workspace_html_files()
                self.send_json({"files": files})

            elif path == "/api/transcript":
                default_id = get_latest_conversation_id()
                cid = query.get("id", [default_id])[0]
                since = int(query.get("since", [0])[0])
                data = get_transcript(cid, since)
                self.send_json(data)

        else:
            self.send_error(404, "Endpoint Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length)
        data = {}
        if body_bytes:
            try:
                data = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                pass

        # PIN Authentication endpoint
        if path == "/api/auth":
            submitted_pin = str(data.get("pin", "")).strip()
            correct_pin = get_configured_pin()
            if submitted_pin == correct_pin:
                token = secrets.token_hex(20)
                VALID_TOKENS.add(token)
                self.send_json({"status": "ok", "token": token})
            else:
                self.send_json({"error": "Invalid PIN"}, code=403)
            return

        # All other POST endpoints require authentication
        if not self.check_auth():
            self.send_json({"error": "Unauthorized. PIN required.", "auth_required": True}, code=401)
            return

        if path == "/api/send":
            default_id = get_latest_conversation_id()
            cid = data.get("conversation_id", default_id).strip()
            content = data.get("content", "").strip()
            image_data = data.get("image", None)

            if not content and not image_data:
                self.send_json({"error": "Content or image cannot be empty"}, code=400)
                return

            uploaded_fname = None
            if image_data:
                uploaded_fname, uploaded_fpath = save_uploaded_image(image_data)
                if uploaded_fpath:
                    clean_path = uploaded_fpath.replace("\\", "/")
                    img_tag = f"[Image Attached: file:///{clean_path} | /uploads/{uploaded_fname}]"
                    if content:
                        content = f"{img_tag}\n{content}"
                    else:
                        content = f"{img_tag}\nPlease inspect and analyze this attached photo."

            def execute_send():
                try:
                    subprocess.run(
                        [AGENTAPI_BIN, "send-message", cid, content],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                except Exception as err:
                    print(f"Error in send-message: {err}")

            t = threading.Thread(target=execute_send, daemon=True)
            t.start()
            self.send_json({"status": "sent", "conversation_id": cid, "content": content, "uploaded_image": uploaded_fname})

        elif path == "/api/new_conversation":
            prompt = data.get("prompt", "").strip()
            model = data.get("model", "flash").strip()
            if not prompt:
                self.send_json({"error": "Prompt cannot be empty"}, code=400)
                return

            def execute_new():
                try:
                    subprocess.run(
                        [AGENTAPI_BIN, "new-conversation", f"--model={model}", prompt],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                except Exception as err:
                    print(f"Error in new-conversation: {err}")

            t = threading.Thread(target=execute_new, daemon=True)
            t.start()
            self.send_json({"status": "starting", "prompt": prompt})

        elif path == "/api/exec_terminal":
            command = data.get("command", "").strip()
            if not command:
                self.send_json({"error": "Command cannot be empty"}, code=400)
                return

            try:
                if sys.platform == "win32":
                    runner = ["powershell", "-NoProfile", "-Command", command]
                else:
                    runner = ["/bin/sh", "-c", command]

                res = subprocess.run(
                    runner,
                    cwd=WORKSPACE_DIR,
                    capture_output=True,
                    text=True,
                    timeout=20
                )
                self.send_json({
                    "stdout": res.stdout,
                    "stderr": res.stderr,
                    "code": res.returncode
                })
            except subprocess.TimeoutExpired:
                self.send_json({"error": "Command timed out (20s limit)"}, code=408)
            except Exception as e:
                self.send_json({"error": str(e)}, code=500)

        else:
            self.send_error(404, "Endpoint Not Found")

    def serve_file(self, file_path, content_type):
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error reading file: {e}")

def start_telegram_bot_service():
    if '--from-bot' in sys.argv:
        return None
    cfg_file = os.path.join(BASE_DIR, "telegram_config.json")
    if os.path.isfile(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                token = cfg.get("bot_token")
                if token and len(token) > 10 and token != "YOUR_TELEGRAM_BOT_TOKEN_HERE":
                    from telegram_bot import TelegramBot
                    bot = TelegramBot(token)
                    t = threading.Thread(target=bot.start, daemon=True)
                    t.start()
                    return bot
        except Exception as e:
            print(f"  [!] Telegram bot init error: {e}")
    return None

def run_server():
    server_address = ("0.0.0.0", PORT)
    httpd = ThreadingHTTPServer(server_address, RemoteHandler)
    
    # Start Cloudflare Tunnel for Cellular/Anywhere access
    start_cloudflared_tunnel()

    # Start Telegram Bot if configured
    start_telegram_bot_service()

    ips = get_network_ips()
    print("=" * 60)
    print("  [+] ANTIGRAVITY MOBILE REMOTE SERVER RUNNING")
    print(f"  🔐 Security PIN  : {get_configured_pin()} (Edit pin.txt to change)")
    print("=" * 60)
    for item in ips:
        print(f"  -> {item['type']:<28}: {item['url']}")
    print("=" * 60)
    print("  Open the URL on your mobile phone (Works over Wi-Fi OR Mobile Data)!")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        if TUNNEL_PROCESS:
            TUNNEL_PROCESS.terminate()
        httpd.server_close()

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    run_server()
