"""
Antigravity Telegram Bot (Supervisor & Controller)
=================================================
Provides real-time system monitoring, instant links, QR codes,
PIN management, remote execution, and service start/stop/restart
controls directly via Telegram with custom keyboard buttons.

Zero external dependencies required (Pure Python 3 standard library).
"""

import os
import sys
import json
import time
import socket
import shutil
import urllib.request
import urllib.parse
import subprocess
import threading
import uuid
import html

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

CONFIG_FILE = os.path.join(BASE_DIR, "telegram_config.json")
TUNNEL_FILE = os.path.join(BASE_DIR, "tunnel_url.txt")
PIN_FILE = os.path.join(BASE_DIR, "pin.txt")
QR_FILE = os.path.join(BASE_DIR, "qr_internet.png")
SERVER_PY = os.path.join(BASE_DIR, "server.py")
AGENTAPI_BAT = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity", "bin", "agentapi.bat")
WORKSPACE_DIR = r"D:\_ide\Antigravity"
BRAIN_DIR = os.environ.get("ANTIGRAVITY_BRAIN", os.path.join(os.path.expanduser("~"), ".gemini", "antigravity", "brain"))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

def escape_html(text):
    return html.escape(str(text)) if text else ""

DEFAULT_KEYBOARD = {
    "keyboard": [
        [{"text": "🔗 Get Link"}, {"text": "📊 Status"}, {"text": "📈 Limits"}],
        [{"text": "🔄 Restart Service"}, {"text": "🟢 Start Service"}, {"text": "🛑 Stop Service"}]
    ],
    "resize_keyboard": True,
    "is_persistent": True
}

def load_config():
    default_config = {
        "bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "allowed_chat_ids": []
    }
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                default_config.update(data)
        except Exception:
            pass
    else:
        save_config(default_config)
    return default_config

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")

def get_current_pin():
    if os.path.isfile(PIN_FILE):
        try:
            with open(PIN_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return "1234"

def get_tunnel_url():
    if os.path.isfile(TUNNEL_FILE):
        try:
            with open(TUNNEL_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return None

def is_server_running():
    try:
        s = socket.create_connection(("127.0.0.1", 8080), timeout=1)
        s.close()
        return True
    except Exception:
        return False

def stop_server_service():
    # 1. Kill cloudflared
    try:
        subprocess.run(["powershell", "-Command", "Stop-Process -Name 'cloudflared' -Force -ErrorAction SilentlyContinue"], timeout=5)
    except Exception:
        pass
    # 2. Kill port 8080 listeners
    try:
        subprocess.run(["powershell", "-Command", "Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"], timeout=5)
    except Exception:
        pass
    time.sleep(1)

def start_server_service():
    if is_server_running():
        return True

    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)

    cmd = [sys.executable, SERVER_PY, "--from-bot"]
    try:
        subprocess.Popen(
            cmd,
            cwd=BASE_DIR,
            creationflags=flags,
            close_fds=True
        )
        return True
    except Exception as e:
        print(f"Error launching server: {e}")
        return False

def multipart_encode(fields, files):
    boundary = uuid.uuid4().hex
    crlf = b"\r\n"
    lines = []
    for key, val in fields.items():
        lines.append(f"--{boundary}".encode())
        lines.append(f'Content-Disposition: form-data; name="{key}"'.encode())
        lines.append(b"")
        lines.append(str(val).encode())
    for key, (filename, filedata, content_type) in files.items():
        lines.append(f"--{boundary}".encode())
        lines.append(f'Content-Disposition: form-data; name="{key}"; filename="{filename}"'.encode())
        lines.append(f"Content-Type: {content_type}".encode())
        lines.append(b"")
        lines.append(filedata)
    lines.append(f"--{boundary}--".encode())
    lines.append(b"")
    body = crlf.join(lines)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type

class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.last_update_id = 0
        self.config = load_config()
        self.running = True
        self.is_restarting = False
        self.pending_prompts = {}

    def call_api(self, endpoint, data=None, files=None):
        url = f"{self.api_url}/{endpoint}"
        try:
            if files:
                body, ctype = multipart_encode(data or {}, files)
                req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
            elif data:
                body = json.dumps(data).encode("utf-8")
                req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            else:
                req = urllib.request.Request(url)
            
            with urllib.request.urlopen(req, timeout=35) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def send_message(self, chat_id, text, parse_mode="HTML", with_keyboard=True, reply_markup=None):
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        elif with_keyboard:
            payload["reply_markup"] = DEFAULT_KEYBOARD
        return self.call_api("sendMessage", payload)

    def edit_message_text(self, chat_id, message_id, text, parse_mode="HTML", reply_markup=None):
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self.call_api("editMessageText", payload)

    def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        payload = {
            "callback_query_id": callback_query_id
        }
        if text:
            payload["text"] = text
            payload["show_alert"] = show_alert
        return self.call_api("answerCallbackQuery", payload)

    def send_photo(self, chat_id, photo_path, caption="", with_keyboard=True):
        if not os.path.isfile(photo_path):
            return self.send_message(chat_id, caption, with_keyboard=with_keyboard)
        try:
            with open(photo_path, "rb") as f:
                photo_data = f.read()
            data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
            if with_keyboard:
                data["reply_markup"] = json.dumps(DEFAULT_KEYBOARD)
            return self.call_api(
                "sendPhoto",
                data=data,
                files={"photo": ("qr.png", photo_data, "image/png")}
            )
        except Exception as e:
            return self.send_message(chat_id, f"{caption}\n(Error sending QR image: {e})", with_keyboard=with_keyboard)

    def broadcast(self, text, photo_path=None):
        for cid in self.config.get("allowed_chat_ids", []):
            if photo_path and os.path.isfile(photo_path):
                self.send_photo(cid, photo_path, caption=text)
            else:
                self.send_message(cid, text)

    def is_authorized(self, chat_id):
        allowed = self.config.get("allowed_chat_ids", [])
        return (str(chat_id) in [str(x) for x in allowed])

    def authorize_chat(self, chat_id):
        allowed = self.config.get("allowed_chat_ids", [])
        if chat_id not in allowed:
            allowed.append(chat_id)
            self.config["allowed_chat_ids"] = allowed
            save_config(self.config)

    def handle_command(self, chat_id, text):
        clean_text = text.strip()
        parts = clean_text.split()
        cmd = parts[0].lower() if parts else ""
        args = parts[1:] if len(parts) > 1 else []
        current_pin = get_current_pin()

        # Authorization via PIN
        if cmd == "/start":
            if args and args[0] == current_pin:
                self.authorize_chat(chat_id)
                self.send_message(
                    chat_id,
                    f"✅ <b>Access Granted!</b>\nYour Telegram chat is authorized to control your Antigravity workstation.\n\nUse the buttons below or type /help to get started."
                )
                self.cmd_link(chat_id)
                return
            elif self.is_authorized(chat_id):
                self.send_message(
                    chat_id,
                    "👋 <b>Welcome back!</b>\nYour chat is authorized. Use the control buttons below."
                )
                self.cmd_link(chat_id)
                return
            else:
                self.send_message(
                    chat_id,
                    f"🔒 <b>Authentication Required</b>\nPlease send your 4-digit PIN to authorize this chat:\n<code>/start &lt;PIN&gt;</code>\n\nExample: <code>/start {current_pin}</code>",
                    with_keyboard=False
                )
                return

        # Check authorization for all other commands
        if not self.is_authorized(chat_id):
            if clean_text == current_pin or (args and args[0] == current_pin):
                self.authorize_chat(chat_id)
                self.send_message(chat_id, "✅ <b>Access Granted!</b> Your chat has been verified.")
                self.cmd_link(chat_id)
                return
            self.send_message(
                chat_id,
                "⛔ <b>Unauthorized</b>\nPlease enter your PIN to continue:\n<code>/start &lt;PIN&gt;</code>",
                with_keyboard=False
            )
            return

        # Map button texts to commands
        if clean_text == "🔗 Get Link": cmd = "/link"
        elif clean_text == "📊 Status": cmd = "/status"
        elif clean_text == "📈 Limits": cmd = "/limits"
        elif clean_text == "🔄 Restart Service": cmd = "/restart"
        elif clean_text == "🟢 Start Service": cmd = "/start_service"
        elif clean_text == "🛑 Stop Service": cmd = "/stop"

        # Authorized commands
        if cmd in ["/link", "/url"]:
            self.cmd_link(chat_id)
        elif cmd in ["/status", "/stats"]:
            self.cmd_status(chat_id)
        elif cmd in ["/limits", "/limit", "/quota"]:
            self.cmd_limits(chat_id)
        elif cmd in ["/restart", "/restart_service"]:
            self.cmd_restart(chat_id)
        elif cmd in ["/start_service", "/startserver"]:
            self.cmd_start_service(chat_id)
        elif cmd in ["/stop", "/stop_service"]:
            self.cmd_stop_service(chat_id)
        elif cmd == "/pin":
            self.cmd_pin(chat_id, args)
        elif cmd in ["/cmd", "/shell"]:
            self.cmd_shell(chat_id, " ".join(args))
        elif cmd in ["/ask", "/prompt"]:
            self.cmd_ask(chat_id, " ".join(args))
        elif cmd in ["/help", "/menu"]:
            self.cmd_help(chat_id)
        else:
            self.send_message(
                chat_id,
                "❓ Unknown command. Use the control buttons below or type /help."
            )

    def cmd_link(self, chat_id):
        if not is_server_running():
            self.send_message(
                chat_id,
                "⚠️ <b>Server is Stopped</b>\nTap <b>🟢 Start Service</b> to launch the server and generate a link."
            )
            return

        url = get_tunnel_url()
        pin = get_current_pin()
        if url:
            caption = (
                f"🚀 <b>Antigravity Remote is Live!</b>\n\n"
                f"🔗 <b>Link:</b> <a href=\"{url}\">{url}</a>\n"
                f"🔑 <b>Security PIN:</b> <code>{pin}</code>\n\n"
                f"📶 <b>Local Wi-Fi:</b> <code>http://192.168.1.11:8080</code>\n"
                f"🔒 <b>Tailscale:</b> <code>http://100.75.138.38:8080</code>\n\n"
                f"<i>Scan QR or tap the link to connect!</i>"
            )
            self.send_photo(chat_id, QR_FILE, caption=caption)
        else:
            self.send_message(
                chat_id,
                f"⏳ <b>Tunnel Initializing...</b>\nPlease wait a few seconds and tap <b>🔗 Get Link</b> again."
            )

    def cmd_status(self, chat_id):
        running = is_server_running()
        status_dot = "🟢 Running" if running else "🔴 Stopped"
        pin = get_current_pin()
        tunnel = get_tunnel_url() or "Offline"

        # Hardware metrics
        total_ram = 0
        used_ram = 0
        ram_pct = 0
        try:
            ps_cmd = "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize, FreePhysicalMemory | ConvertTo-Json"
            res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=5)
            mem = json.loads(res.stdout)
            total_mb = mem["TotalVisibleMemorySize"] // 1024
            free_mb = mem["FreePhysicalMemory"] // 1024
            used_mb = total_mb - free_mb
            total_ram = round(total_mb / 1024, 1)
            used_ram = round(used_mb / 1024, 1)
            ram_pct = int((used_mb / total_mb) * 100)
        except Exception:
            pass

        disks = []
        for d in ["C:", "D:"]:
            if os.path.exists(d):
                try:
                    tot, used, free = shutil.disk_usage(d)
                    disks.append(f"  • <b>{d}</b>: {free // (2**30)}GB free / {tot // (2**30)}GB")
                except Exception:
                    pass

        disks_str = "\n".join(disks) if disks else "  • No storage detected"
        msg = (
            f"🖥️ <b>Workstation System Status:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 <b>Mobile Service:</b> {status_dot}\n"
            f"💻 <b>Host:</b> <code>{socket.gethostname()}</code>\n"
            f"⚡ <b>RAM:</b> <code>{used_ram}GB / {total_ram}GB ({ram_pct}%)</code>\n"
            f"💾 <b>Storage:</b>\n{disks_str}\n"
            f"🔗 <b>Active Tunnel:</b> {tunnel}\n"
            f"🔑 <b>PIN:</b> <code>{pin}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━"
        )
        self.send_message(chat_id, msg)

    def cmd_limits(self, chat_id):
        from server import get_limit_metrics
        lim = get_limit_metrics()
        r5 = lim.get("rolling_5h", {})
        rw = lim.get("rolling_week", {})
        disks_str = "\n".join([f"  • <b>{d['drive']}</b>: {d['free_gb']}GB free / {d['total_gb']}GB ({d['used_pct']}%)" for d in lim.get("disks", [])])

        msg = (
            f"📊 <b>Antigravity Model Quotas &amp; Usage Limits:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ <b>5-Hour Rolling Limit (Burst Quota):</b>\n"
            f"  • Remaining: <b>{r5.get('left_requests', 0)} requests left</b>\n"
            f"  • Consumed: {r5.get('used_requests', 0)} / {r5.get('limit_requests', 250)} ({r5.get('used_pct', '0%')})\n"
            f"  • 5h Tokens: {r5.get('total_tokens', 0):,} tokens\n"
            f"  • Earliest Reset: in <b>{r5.get('resets_in', 'Rolling')}</b>\n\n"
            f"📅 <b>Weekly Limit (7-Day Rolling):</b>\n"
            f"  • Remaining: <b>{rw.get('left_requests', 0)} requests left</b>\n"
            f"  • Consumed: {rw.get('used_requests', 0)} / {rw.get('limit_requests', 1500)} ({rw.get('used_pct', '0%')})\n"
            f"  • 7d Tokens: {rw.get('total_tokens', 0):,} tokens\n\n"
            f"🧠 <b>Session Context Window:</b>\n"
            f"  • Model: <code>{lim['model']}</code>\n"
            f"  • Context Left: <b>{lim.get('context_left_tokens', 0):,} tokens left</b>\n"
            f"  • Context Used: {lim['context_tokens']:,} / {lim['context_limit']:,} ({lim['context_used_pct']})\n"
            f"  • Session Total: {lim['session_total_tokens']:,} tokens ({lim['session_steps']} turns)\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🖥️ <b>Workstation Limits:</b>\n"
            f"⚡ <b>RAM:</b> <code>{lim['ram']['used_gb']}GB / {lim['ram']['total_gb']}GB ({lim['ram']['pct']})</code>\n"
            f"💾 <b>Storage:</b>\n{disks_str}\n"
            f"━━━━━━━━━━━━━━━━━━━"
        )
        self.send_message(chat_id, msg)

    def cmd_restart(self, chat_id):
        if self.is_restarting:
            self.send_message(chat_id, "⏳ Restart is already in progress, please wait...")
            return

        self.is_restarting = True
        self.send_message(chat_id, "🔄 <b>Restarting Service...</b>\nClosing existing processes and creating a fresh Cloudflare tunnel. Please wait 5-8 seconds...")

        def do_restart():
            try:
                # Remove old tunnel file to detect new one
                old_url = get_tunnel_url()
                if os.path.exists(TUNNEL_FILE):
                    try: os.remove(TUNNEL_FILE)
                    except Exception: pass

                stop_server_service()
                start_server_service()

                # Poll for fresh tunnel URL
                new_url = None
                for _ in range(15):
                    time.sleep(1)
                    curr = get_tunnel_url()
                    if curr and curr != old_url:
                        new_url = curr
                        break

                pin = get_current_pin()
                if new_url:
                    caption = (
                        f"✅ <b>Server Restarted Successfully!</b>\n\n"
                        f"🔗 <b>New Link:</b> <a href=\"{new_url}\">{new_url}</a>\n"
                        f"🔑 <b>Security PIN:</b> <code>{pin}</code>\n\n"
                        f"<i>Tap the link above to open on mobile!</i>"
                    )
                    self.send_photo(chat_id, QR_FILE, caption=caption)
                else:
                    self.send_message(chat_id, f"⚠️ Server started on local port 8080, but tunnel is still initializing. Tap <b>🔗 Get Link</b> in a moment.")
            finally:
                self.is_restarting = False

        threading.Thread(target=do_restart, daemon=True).start()

    def cmd_start_service(self, chat_id):
        if is_server_running():
            url = get_tunnel_url()
            self.send_message(chat_id, f"🟢 <b>Service is already running!</b>\nLink: {url}")
            return

        self.send_message(chat_id, "🟢 <b>Starting Antigravity Mobile Service...</b>")
        start_server_service()

        def wait_and_send():
            for _ in range(12):
                time.sleep(1)
                url = get_tunnel_url()
                if url:
                    self.cmd_link(chat_id)
                    return
            self.send_message(chat_id, "🟢 Service started. Tap <b>🔗 Get Link</b> to fetch the URL.")

        threading.Thread(target=wait_and_send, daemon=True).start()

    def cmd_stop_service(self, chat_id):
        if not is_server_running():
            self.send_message(chat_id, "⚪ <b>Service is already stopped.</b>")
            return

        stop_server_service()
        self.send_message(
            chat_id,
            "🛑 <b>Antigravity Mobile Server & Tunnel Stopped.</b>\nTap <b>🟢 Start Service</b> or <b>🔄 Restart Service</b> anytime to turn it back on."
        )

    def cmd_pin(self, chat_id, args):
        if not args:
            pin = get_current_pin()
            self.send_message(chat_id, f"🔑 <b>Current PIN:</b> <code>{pin}</code>\nTo change: <code>/pin &lt;new_pin&gt;</code>")
            return
        new_pin = args[0].strip()
        if len(new_pin) < 4:
            self.send_message(chat_id, "⚠️ PIN must be at least 4 digits.")
            return
        try:
            with open(PIN_FILE, "w", encoding="utf-8") as f:
                f.write(new_pin)
            self.send_message(chat_id, f"✅ <b>PIN updated to:</b> <code>{new_pin}</code>")
        except Exception as e:
            self.send_message(chat_id, f"❌ Failed to update PIN: {e}")

    def cmd_shell(self, chat_id, command):
        if not command:
            self.send_message(chat_id, "Usage: <code>/cmd &lt;powershell_command&gt;</code>\nExample: <code>/cmd git status</code>")
            return
        self.send_message(chat_id, f"⏳ Executing: <code>{command}</code>...")
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                cwd=WORKSPACE_DIR,
                capture_output=True,
                text=True,
                timeout=25
            )
            out = res.stdout or ""
            err = res.stderr or ""
            full_out = (out + ("\nSTDERR:\n" + err if err else "")).strip()
            if not full_out:
                full_out = "(Command executed with no output)"
            if len(full_out) > 3500:
                full_out = full_out[:3500] + "\n...(output truncated)"
            self.send_message(chat_id, f"<pre>{full_out}</pre>")
        except subprocess.TimeoutExpired:
            self.send_message(chat_id, "⏱️ Command timed out (25s limit).")
        except Exception as e:
            self.send_message(chat_id, f"❌ Error: {e}")

    def cmd_ask(self, chat_id, prompt):
        if not prompt or not prompt.strip():
            self.send_message(
                chat_id,
                "💡 <b>Usage:</b> <code>/ask &lt;instruction for Antigravity&gt;</code>\n\n"
                "Example: <code>/ask Add dark mode toggle</code>\n"
                "The bot will ask you which session to send the prompt to!"
            )
            return

        clean_prompt = prompt.strip()
        self.pending_prompts[str(chat_id)] = clean_prompt

        try:
            from server import list_conversations
            convs = list_conversations()
        except Exception:
            convs = []

        keyboard = []
        sessions_summary = []

        # Offer up to top 4 recent conversations
        for idx, c in enumerate(convs[:4], 1):
            cid = c.get("id", "")
            raw_title = c.get("title", cid[:8])
            is_curr = c.get("is_current", False)

            icon = "⭐" if is_curr else f"{idx}️⃣"
            prefix = "[Current] " if is_curr else ""

            # Label for inline button (short enough for mobile screen)
            btn_title = raw_title if len(raw_title) <= 26 else (raw_title[:25] + "…")
            btn_text = f"{icon} {prefix}{btn_title}"
            keyboard.append([{"text": btn_text, "callback_data": f"ask_cid:{cid}"}])

            desc = f"{icon} <b>{prefix}{escape_html(raw_title)}</b>"
            sessions_summary.append(desc)

        keyboard.append([{"text": "✨ Start New Session", "callback_data": "ask_cid:new"}])
        keyboard.append([{"text": "❌ Cancel", "callback_data": "ask_cid:cancel"}])

        preview_prompt = clean_prompt if len(clean_prompt) <= 120 else (clean_prompt[:117] + "...")
        sessions_block = "\n".join(sessions_summary) if sessions_summary else "<i>No existing sessions found</i>"

        msg = (
            f"🎯 <b>Select Destination Session for Prompt:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💬 <i>\"{escape_html(preview_prompt)}\"</i>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Recent Sessions:</b>\n{sessions_block}\n\n"
            f"👇 <i>Tap a button below to dispatch this prompt:</i>"
        )

        self.send_message(chat_id, msg, reply_markup={"inline_keyboard": keyboard})

    def handle_callback(self, cb):
        cb_id = cb.get("id")
        data = cb.get("data", "")
        msg = cb.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        message_id = msg.get("message_id")

        if not cb_id:
            return

        # Acknowledge immediately to stop loading spinner
        self.answer_callback_query(cb_id)

        if not chat_id or not self.is_authorized(chat_id):
            return

        if not data.startswith("ask_cid:"):
            return

        target = data[len("ask_cid:"):]
        chat_id_str = str(chat_id)
        prompt = self.pending_prompts.pop(chat_id_str, None)

        if target == "cancel":
            self.edit_message_text(
                chat_id,
                message_id,
                "❌ <b>Prompt cancelled.</b> No message was sent.",
                reply_markup={"inline_keyboard": []}
            )
            return

        if not prompt:
            self.edit_message_text(
                chat_id,
                message_id,
                "⚠️ <b>Prompt expired or already sent.</b>\nPlease type <code>/ask &lt;prompt&gt;</code> to try again.",
                reply_markup={"inline_keyboard": []}
            )
            return

        safe_prompt = escape_html(prompt[:120] + ("..." if len(prompt) > 120 else ""))

        if target == "new":
            self.edit_message_text(
                chat_id,
                message_id,
                f"✨ <b>Starting New Antigravity Session...</b>\n\n💬 <i>\"{safe_prompt}\"</i>\n\n⏳ Spawning new session with agentapi...",
                reply_markup={"inline_keyboard": []}
            )
            def run_new():
                try:
                    existing_cids = set(os.listdir(BRAIN_DIR)) if os.path.exists(BRAIN_DIR) else set()
                    res = subprocess.run([AGENTAPI_BAT, "new-conversation", prompt], capture_output=True, text=True, timeout=25)
                    new_cid = None
                    for _ in range(12):
                        time.sleep(1)
                        if os.path.exists(BRAIN_DIR):
                            curr_cids = set(os.listdir(BRAIN_DIR))
                            diff = curr_cids - existing_cids
                            if diff:
                                new_cid = list(diff)[0]
                                break
                    if not new_cid:
                        from server import get_latest_conversation_id
                        new_cid = get_latest_conversation_id()

                    self.edit_message_text(
                        chat_id,
                        message_id,
                        f"⏳ <b>Antigravity New Session Active!</b>\n💬 <i>\"{safe_prompt}\"</i>\n\n<i>Waiting for agent response...</i>",
                        reply_markup={"inline_keyboard": []}
                    )
                    self.monitor_and_send_final_output(chat_id, message_id, new_cid, -1, prompt)
                except Exception as e:
                    self.send_message(chat_id, f"❌ Failed to create new session: {escape_html(str(e))}")
            threading.Thread(target=run_new, daemon=True).start()

        else:
            cid = target
            initial_step = self.get_latest_step_index(cid)
            self.edit_message_text(
                chat_id,
                message_id,
                f"🚀 <b>Dispatching to Session</b> <code>{cid[:8]}</code>...\n\n💬 <i>\"{safe_prompt}\"</i>\n\n⏳ Delivering prompt via agentapi...",
                reply_markup={"inline_keyboard": []}
            )
            def run_send():
                try:
                    res = subprocess.run([AGENTAPI_BAT, "send-message", cid, prompt], capture_output=True, text=True, timeout=20)
                    self.edit_message_text(
                        chat_id,
                        message_id,
                        f"⏳ <b>Prompt Received by Antigravity!</b>\n💬 <i>\"{safe_prompt}\"</i>\n\n<i>Working on your request... I will post the response here!</i>",
                        reply_markup={"inline_keyboard": []}
                    )
                    self.monitor_and_send_final_output(chat_id, message_id, cid, initial_step, prompt)
                except Exception as e:
                    self.send_message(chat_id, f"❌ Failed delivering message: {escape_html(str(e))}")
            threading.Thread(target=run_send, daemon=True).start()

    def get_latest_step_index(self, cid):
        if not cid:
            return -1
        cpath = os.path.join(BRAIN_DIR, cid, ".system_generated", "logs", "transcript.jsonl")
        if not os.path.isfile(cpath):
            return -1
        max_idx = -1
        try:
            with open(cpath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            obj = json.loads(line)
                            idx = obj.get("step_index", -1)
                            if idx > max_idx:
                                max_idx = idx
                        except Exception:
                            pass
        except Exception:
            pass
        return max_idx

    def send_telegram_response_chunks(self, chat_id, text):
        if not text or not text.strip():
            self.send_message(chat_id, "🤖 <i>(Antigravity finished with no text output)</i>")
            return

        clean_text = text.strip()
        max_chunk = 3800

        def split_into_chunks(s, max_len):
            if len(s) <= max_len:
                return [s]
            chunks = []
            lines = s.split("\n")
            curr = ""
            for line in lines:
                if len(curr) + len(line) + 1 > max_len:
                    if curr:
                        chunks.append(curr)
                    curr = line
                else:
                    curr = (curr + "\n" + line) if curr else line
            if curr:
                chunks.append(curr)
            return chunks

        chunks = split_into_chunks(clean_text, max_chunk)
        for i, chunk in enumerate(chunks, 1):
            part_header = f" <i>(Part {i}/{len(chunks)})</i>" if len(chunks) > 1 else ""
            html_msg = (
                f"🤖 <b>Antigravity Response{part_header}:</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"{escape_html(chunk)}\n"
                f"━━━━━━━━━━━━━━━━━━━"
            )
            res = self.send_message(chat_id, html_msg, parse_mode="HTML")
            if not res.get("ok"):
                plain_msg = f"🤖 Antigravity Response{part_header}:\n━━━━━━━━━━━━━━━━━━━\n{chunk}\n━━━━━━━━━━━━━━━━━━━"
                self.send_message(chat_id, plain_msg, parse_mode=None)
            time.sleep(0.3)

    def monitor_and_send_final_output(self, chat_id, message_id, cid, initial_step_index, prompt):
        poll_start = time.time()
        last_status_update = time.time()
        last_tool_name = ""
        timeout_seconds = 360

        while time.time() - poll_start < timeout_seconds:
            time.sleep(2.5)

            if not cid:
                break

            cpath = os.path.join(BRAIN_DIR, cid, ".system_generated", "logs", "transcript.jsonl")
            if not os.path.isfile(cpath):
                continue

            steps_after = []
            try:
                with open(cpath, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                obj = json.loads(line)
                                if obj.get("step_index", -1) > initial_step_index:
                                    steps_after.append(obj)
                            except Exception:
                                pass
            except Exception:
                continue

            if not steps_after:
                continue

            # Check for running tools to show live feedback in Telegram
            for s in steps_after:
                tcalls = s.get("tool_calls", [])
                if tcalls:
                    last_tc = tcalls[-1]
                    tname = last_tc.get("name", "tool")
                    if tname != last_tool_name:
                        last_tool_name = tname
                        if time.time() - last_status_update > 5:
                            self.edit_message_text(
                                chat_id,
                                message_id,
                                f"⏳ <b>Antigravity is working...</b>\n"
                                f"⚡ Running: <code>{escape_html(last_tool_name)}</code> (Step {s.get('step_index')})\n\n"
                                f"<i>Output will be posted here automatically!</i>",
                                reply_markup={"inline_keyboard": []}
                            )
                            last_status_update = time.time()

            # Check if final response is ready (PLANNER_RESPONSE with non-empty content and no tool calls)
            final_candidate = None
            for s in reversed(steps_after):
                if s.get("type") == "PLANNER_RESPONSE":
                    cnt = s.get("content", "").strip()
                    tcalls = s.get("tool_calls", [])
                    if cnt and len(tcalls) == 0:
                        final_candidate = cnt
                        break

            if final_candidate:
                time.sleep(1.5)
                self.edit_message_text(
                    chat_id,
                    message_id,
                    f"✅ <b>Antigravity Finished!</b> Response below 👇",
                    reply_markup={"inline_keyboard": []}
                )
                self.send_telegram_response_chunks(chat_id, final_candidate)
                return

        # Timeout notice
        self.edit_message_text(
            chat_id,
            message_id,
            f"⏱️ <b>Response Taking Longer Than Usual</b>\n"
            f"Antigravity is still executing complex tasks. Tap <b>🔗 Get Link</b> to monitor live in mobile chat!",
            reply_markup={"inline_keyboard": []}
        )

    def handle_photo(self, chat_id, photo_list, caption):
        if not self.is_authorized(chat_id):
            self.send_message(chat_id, "⛔ Unauthorized. Use /start <PIN> to authorize.")
            return

        if not photo_list:
            return

        largest = photo_list[-1]
        file_id = largest.get("file_id")
        file_res = self.call_api("getFile", {"file_id": file_id})
        if not file_res.get("ok"):
            self.send_message(chat_id, "❌ Failed to retrieve photo from Telegram.")
            return

        file_path = file_res["result"].get("file_path", "")
        token = self.token
        download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"

        ext = os.path.splitext(file_path)[1] or ".jpg"
        local_name = f"photo_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
        local_path = os.path.join(UPLOADS_DIR, local_name)

        try:
            req = urllib.request.Request(download_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(local_path, "wb") as f:
                f.write(resp.read())
        except Exception as e:
            self.send_message(chat_id, f"❌ Failed to download photo: {e}")
            return

        clean_path = local_path.replace("\\", "/")
        user_prompt = caption.strip() if caption else "Please inspect and analyze this attached photo."
        full_prompt = f"[Image Attached: file:///{clean_path} | /uploads/{local_name}]\n{user_prompt}"

        self.send_message(chat_id, "📸 <b>Photo received!</b>")
        self.cmd_ask(chat_id, full_prompt)

    def cmd_help(self, chat_id):
        msg = (
            f"🤖 <b>Antigravity Telegram Controller</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>/link</b> - Get active Cloudflare link &amp; QR code\n"
            f"📊 <b>/status</b> - Get PC CPU, RAM, and Disk metrics\n"
            f"📈 <b>/limits</b> - View AI context window &amp; token quotas\n"
            f"🔄 <b>/restart</b> - Stop &amp; restart server with fresh tunnel\n"
            f"🟢 <b>/start_service</b> - Start mobile server if stopped\n"
            f"🛑 <b>/stop</b> - Stop mobile server &amp; tunnel\n"
            f"🔑 <b>/pin [new_pin]</b> - View or update security PIN\n"
            f"💻 <b>/cmd &lt;command&gt;</b> - Run PowerShell on workstation\n"
            f"🤖 <b>/ask &lt;prompt&gt;</b> - Send prompt (interactive session picker)\n"
            f"━━━━━━━━━━━━━━━━━━━"
        )
        self.send_message(chat_id, msg)

    def watch_tunnel_changes(self):
        last_url = get_tunnel_url()
        while self.running:
            time.sleep(3)
            current_url = get_tunnel_url()
            if current_url and current_url != last_url and not self.is_restarting:
                last_url = current_url
                pin = get_current_pin()
                msg = (
                    f"⚡ <b>Antigravity Server Restarted!</b>\n\n"
                    f"🔗 <b>New Link:</b> <a href=\"{current_url}\">{current_url}</a>\n"
                    f"🔑 <b>PIN:</b> <code>{pin}</code>\n\n"
                    f"<i>Tap the link or scan QR to connect!</i>"
                )
                self.broadcast(msg, photo_path=QR_FILE)

    def start(self):
        me = self.call_api("getMe")
        if not me.get("ok"):
            print(f"  [!] Invalid Telegram Bot Token: {me.get('error')}")
            return False

        bot_name = me["result"].get("username", "AntigravityBot")
        print("=" * 60)
        print(f"  🤖 TELEGRAM SUPERVISOR BOT RUNNING: @{bot_name}")
        print("=" * 60)
        print(f"  👉 Open Telegram and tap buttons to control your server!")
        print("=" * 60)

        # Start background tunnel change watcher
        tw = threading.Thread(target=self.watch_tunnel_changes, daemon=True)
        tw.start()

        # Polling loop
        while self.running:
            try:
                updates = self.call_api("getUpdates", data={
                    "offset": self.last_update_id + 1,
                    "timeout": 20
                })
                if updates.get("ok"):
                    for item in updates.get("result", []):
                        self.last_update_id = item["update_id"]
                        cb = item.get("callback_query")
                        if cb:
                            self.handle_callback(cb)
                            continue
                        msg = item.get("message")
                        if msg:
                            chat_id = msg.get("chat", {}).get("id")
                            if "photo" in msg:
                                self.handle_photo(chat_id, msg["photo"], msg.get("caption", ""))
                            elif "text" in msg:
                                self.handle_command(chat_id, msg["text"])
            except Exception as e:
                time.sleep(2)

def main():
    cfg = load_config()
    token = cfg.get("bot_token")
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("Please configure bot_token in telegram_config.json")
        return

    bot = TelegramBot(token)
    bot.start()

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    main()
