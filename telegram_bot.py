"""
Antigravity Telegram Bot
========================
Provides real-time system monitoring, instant links, QR codes,
PIN management, and remote execution directly via Telegram.

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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "telegram_config.json")
TUNNEL_FILE = os.path.join(BASE_DIR, "tunnel_url.txt")
PIN_FILE = os.path.join(BASE_DIR, "pin.txt")
QR_FILE = os.path.join(BASE_DIR, "qr_internet.png")
AGENTAPI_BAT = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity", "bin", "agentapi.bat")
WORKSPACE_DIR = r"D:\_ide\Antigravity"

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

def get_system_status():
    metrics = {
        "hostname": socket.gethostname(),
        "ram": "Unknown",
        "disks": [],
        "tunnel": get_tunnel_url() or "Offline / Starting...",
        "pin": get_current_pin(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    # RAM
    try:
        ps_cmd = "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize, FreePhysicalMemory | ConvertTo-Json"
        res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=5)
        mem = json.loads(res.stdout)
        total_mb = mem["TotalVisibleMemorySize"] // 1024
        free_mb = mem["FreePhysicalMemory"] // 1024
        used_mb = total_mb - free_mb
        ram_pct = int((used_mb / total_mb) * 100)
        metrics["ram"] = f"{round(used_mb/1024, 1)}GB / {round(total_mb/1024, 1)}GB ({ram_pct}%)"
    except Exception:
        pass

    # Disks
    for d in ["C:", "D:"]:
        if os.path.exists(d):
            try:
                tot, used, free = shutil.disk_usage(d)
                metrics["disks"].append(f"{d} {free // (2**30)}GB free of {tot // (2**30)}GB")
            except Exception:
                pass

    return metrics

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

    def send_message(self, chat_id, text, parse_mode="HTML"):
        return self.call_api("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        })

    def send_photo(self, chat_id, photo_path, caption=""):
        if not os.path.isfile(photo_path):
            return self.send_message(chat_id, caption)
        try:
            with open(photo_path, "rb") as f:
                photo_data = f.read()
            return self.call_api(
                "sendPhoto",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"photo": ("qr.png", photo_data, "image/png")}
            )
        except Exception as e:
            return self.send_message(chat_id, f"{caption}\n(Error sending QR image: {e})")

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
        parts = text.strip().split()
        cmd = parts[0].lower() if parts else ""
        args = parts[1:] if len(parts) > 1 else []

        current_pin = get_current_pin()

        # Authorization via PIN
        if cmd == "/start":
            if args and args[0] == current_pin:
                self.authorize_chat(chat_id)
                self.send_message(
                    chat_id,
                    f"✅ <b>Access Granted!</b>\nYour Telegram chat is now authorized to monitor and control your Antigravity workstation.\n\nType /help to see all commands."
                )
                self.cmd_link(chat_id)
                return
            elif self.is_authorized(chat_id):
                self.send_message(
                    chat_id,
                    "👋 <b>Welcome back!</b>\nYour chat is already authorized. Type /help to see available commands."
                )
                self.cmd_link(chat_id)
                return
            else:
                self.send_message(
                    chat_id,
                    f"🔒 <b>Authentication Required</b>\nPlease send your 4-digit PIN to authorize this chat:\n<code>/start &lt;YOUR_PIN&gt;</code>\n\nExample: <code>/start 2486</code>"
                )
                return

        # Check authorization for all other commands
        if not self.is_authorized(chat_id):
            if cmd == current_pin or (args and args[0] == current_pin):
                self.authorize_chat(chat_id)
                self.send_message(chat_id, "✅ <b>Access Granted!</b> Your chat has been verified.")
                self.cmd_link(chat_id)
                return
            self.send_message(
                chat_id,
                "⛔ <b>Unauthorized</b>\nPlease enter your PIN to continue:\n<code>/start &lt;PIN&gt;</code>"
            )
            return

        # Authorized commands
        if cmd in ["/link", "/url"]:
            self.cmd_link(chat_id)
        elif cmd in ["/status", "/stats"]:
            self.cmd_status(chat_id)
        elif cmd in ["/limits", "/limit", "/quota"]:
            self.cmd_limits(chat_id)
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
                "❓ Unknown command. Type /help to see available commands."
            )

    def cmd_link(self, chat_id):
        url = get_tunnel_url()
        pin = get_current_pin()
        if url:
            caption = (
                f"🚀 <b>Antigravity Remote is Active!</b>\n\n"
                f"🔗 <b>Link:</b> <a href=\"{url}\">{url}</a>\n"
                f"🔑 <b>Security PIN:</b> <code>{pin}</code>\n\n"
                f"📶 <b>Local Wi-Fi:</b> <code>http://192.168.1.11:8080</code>\n"
                f"🔒 <b>Tailscale:</b> <code>http://100.75.138.38:8080</code>\n\n"
                f"<i>Scan the QR code or tap the link to open in your browser!</i>"
            )
            self.send_photo(chat_id, QR_FILE, caption=caption)
        else:
            self.send_message(
                chat_id,
                f"⚠️ <b>Server Tunnel Offline</b>\nStart the server on PC or run <code>START_MOBILE_REMOTE.bat</code>."
            )

    def cmd_status(self, chat_id):
        st = get_system_status()
        disks_str = "\n".join([f"  • {d}" for d in st["disks"]])
        msg = (
            f"🖥️ <b>Workstation Status:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💻 <b>Host:</b> <code>{st['hostname']}</code>\n"
            f"⚡ <b>RAM:</b> <code>{st['ram']}</code>\n"
            f"💾 <b>Disks:</b>\n{disks_str}\n"
            f"🔗 <b>Active Tunnel:</b> <a href=\"{st['tunnel']}\">{st['tunnel']}</a>\n"
            f"🔑 <b>PIN:</b> <code>{st['pin']}</code>\n"
            f"🕒 <b>Time:</b> <code>{st['time']}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━"
        )
        self.send_message(chat_id, msg)

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
            self.send_message(chat_id, "Usage: <code>/cmd &lt;powershell_command&gt;</code>\nExample: <code>/cmd dir</code>")
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
        if not prompt:
            self.send_message(chat_id, "Usage: <code>/ask &lt;instruction for Antigravity&gt;</code>")
            return
        
        # Read active conversation id
        from server import get_latest_conversation_id
        cid = get_latest_conversation_id()
        if not cid:
            self.send_message(chat_id, "❌ No active Antigravity session found.")
            return

        self.send_message(chat_id, f"🚀 <b>Sending to Antigravity:</b>\n<i>{prompt}</i>")
        try:
            subprocess.run([AGENTAPI_BAT, "send-message", cid, prompt], capture_output=True, text=True, timeout=15)
            self.send_message(chat_id, "✅ Instruction received by Antigravity! Watch progress in your mobile link.")
        except Exception as e:
            self.send_message(chat_id, f"❌ Error delivering message: {e}")

    def cmd_limits(self, chat_id):
        from server import get_limit_metrics
        lim = get_limit_metrics()
        disks_str = "\n".join([f"  • <b>{d['drive']}</b>: {d['free_gb']}GB free / {d['total_gb']}GB ({d['used_pct']}%)" for d in lim.get("disks", [])])
        msg = (
            f"📊 <b>Current Limit &amp; Quota Usage:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🧠 <b>Model:</b> <code>{lim['model']}</code>\n"
            f"📏 <b>Context Window:</b> <code>{lim['context_tokens']:,} / {lim['context_limit']:,} ({lim['context_used_pct']})</code>\n"
            f"📥 <b>Input Tokens:</b> <code>{lim['session_input_tokens']:,}</code>\n"
            f"📤 <b>Output Tokens:</b> <code>{lim['session_output_tokens']:,}</code>\n"
            f"⚡ <b>Cache Read:</b> <code>{lim['session_cache_read_tokens']:,}</code>\n"
            f"🔄 <b>Session Total:</b> <code>{lim['session_total_tokens']:,} tokens ({lim['session_steps']} steps)</code>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🖥️ <b>Workstation Limits:</b>\n"
            f"⚡ <b>RAM:</b> <code>{lim['ram']['used_gb']}GB / {lim['ram']['total_gb']}GB ({lim['ram']['pct']})</code>\n"
            f"💾 <b>Storage:</b>\n{disks_str}\n"
            f"━━━━━━━━━━━━━━━━━━━"
        )
        self.send_message(chat_id, msg)

    def cmd_help(self, chat_id):
        msg = (
            f"🤖 <b>Antigravity Telegram Controller</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>/link</b> - Get active Cloudflare link &amp; QR code\n"
            f"📊 <b>/status</b> - Get PC CPU, RAM, and Disk metrics\n"
            f"📈 <b>/limits</b> - View AI context window, token quotas &amp; limits\n"
            f"🔑 <b>/pin [new_pin]</b> - View or update security PIN\n"
            f"💻 <b>/cmd &lt;command&gt;</b> - Run PowerShell on workstation\n"
            f"🤖 <b>/ask &lt;prompt&gt;</b> - Command Antigravity coding agent\n"
            f"❓ <b>/help</b> - Show this help menu\n"
            f"━━━━━━━━━━━━━━━━━━━"
        )
        self.send_message(chat_id, msg)

    def watch_tunnel_changes(self):
        last_url = get_tunnel_url()
        while self.running:
            time.sleep(3)
            current_url = get_tunnel_url()
            if current_url and current_url != last_url:
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
        print(f"  🤖 TELEGRAM BOT RUNNING: @{bot_name}")
        print("=" * 60)
        print(f"  👉 Open Telegram and search for: @{bot_name}")
        print(f"  👉 Send: /start {get_current_pin()} to authorize your chat!")
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
                        msg = item.get("message")
                        if msg and "text" in msg:
                            chat_id = msg["chat"]["id"]
                            text = msg["text"]
                            self.handle_command(chat_id, text)
            except Exception as e:
                time.sleep(2)

def main():
    cfg = load_config()
    token = cfg.get("bot_token")
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("=" * 60)
        print("  🤖 ANTIGRAVITY TELEGRAM BOT SETUP")
        print("=" * 60)
        print("  1. Open Telegram and search for: @BotFather")
        print("  2. Send '/newbot' and follow prompts to get your Bot Token.")
        print(f"  3. Paste the token into: {CONFIG_FILE}")
        print("     or set environment variable TELEGRAM_BOT_TOKEN")
        print("=" * 60)
        
        # Check if user wants to input it now
        if sys.stdin.isatty():
            try:
                entered = input("  Enter your Bot Token (or press Enter to skip): ").strip()
                if entered:
                    cfg["bot_token"] = entered
                    save_config(cfg)
                    token = entered
            except Exception:
                pass
        
        if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
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
