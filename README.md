# 📱 Antigravity Mobile Remote Controller

[![Python 3](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)](LICENSE)
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-Zero%20(Standard%20Lib)-blueviolet?style=for-the-badge)](server.py)
[![Tunnel: Cloudflare](https://img.shields.io/badge/Tunnel-Cloudflare%20Quick%20Tunnel-orange?style=for-the-badge&logo=cloudflare&logoColor=white)](https://cloudflare.com)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=for-the-badge)]()

> A lightweight, mobile-first web hub that connects to Google Antigravity sessions on your workstation. Send instructions, speak voice prompts, stream AI responses in real-time, inspect tool executions, and run host terminal commands directly from your phone — over **Local Wi-Fi**, **Tailscale VPN**, or **Cellular 4G/5G** with zero port forwarding.

---

## ✨ Features

- 🤖 **Telegram Bot Integration**:
  - Receive instant push notifications with new links & QR codes whenever the PC reboots or server restarts.
  - Commands: `/link` (current link & QR), `/status` (CPU, RAM, Disks), `/pin` (view/update PIN), `/ask` (command Antigravity), `/cmd` (run shell commands).
  - Multi-user security: Authorize your chat simply by sending `/start <PIN>`.
- 🔒 **PIN Authentication & Privacy Protection**:
  - Built-in 4-digit PIN lock screen with haptic keypad.
  - Generates secure random session tokens stored in `localStorage`.
  - Configurable via `pin.txt` or `REMOTE_PIN` environment variable (PIN is never committed to Git).
  - Manual lock button (🔒) in header to lock the session instantly.
- 💬 **Live Antigravity Agent Chat**: 
  - Real-time conversation streaming directly from Antigravity session transcripts.
  - Full GitHub-flavored Markdown rendering with syntax highlighting and code blocks.
  - Collapsible tool execution cards showing tool names, parameters, execution status, and stdout/stderr.
- 🌐 **Anywhere Access (No Wi-Fi Required)**:
  - Automatically spins up an encrypted **Cloudflare Quick Tunnel (HTTPS)**.
  - Access your workstation from anywhere in the world on mobile data (4G/5G) without opening firewall ports or router settings.
  - Also detects and supports **Local Wi-Fi LAN** and **Tailscale VPN**.
- 🎙️ **Voice Commands**:
  - One-tap speech-to-text powered by the mobile browser's Web Speech API. Just speak into your phone to command your coding agent.
- 💻 **Direct Shell Terminal**:
  - Run direct PowerShell / Bash commands on your host workstation from your phone (`git status`, `git pull`, `dir`, `tasklist`, etc.) with instant terminal output.
- 🔄 **Multi-Session Switcher**:
  - Automatically discovers all past and active Antigravity conversations.
  - Switch between active sessions on-the-fly or launch a brand new Antigravity agent task directly from your phone.
- 📱 **PWA & Mobile-First Design**:
  - Dark glassmorphism interface matching Antigravity aesthetics.
  - Touch-friendly controls, notch/safe-area support, and "Add to Home Screen" support for a fullscreen native app experience.
- 📦 **Zero External Dependencies**:
  - Pure Python 3 standard library (`http.server`, `urllib`, `subprocess`).
  - No `pip install` required!

---

## 🏗️ Architecture

```
┌──────────────────────┐
│     Mobile Phone     │
│ (Safari / Chrome)    │
└──────────┬───────────┘
           │
           │ HTTPS (Cloudflare Tunnel) / Local Wi-Fi / Tailscale
           ▼
┌──────────────────────────────────────────────┐
│      Antigravity Mobile Server (server.py)   │
│  - Python ThreadingHTTPServer (Port 8080)    │
│  - REST API (/api/transcript, /api/send)     │
└───────────────┬──────────────────────────────┘
                │
        ┌───────┴────────────────────────┐
        ▼                                ▼
┌──────────────────────┐      ┌─────────────────────────┐
│ Antigravity agentapi │      │ Antigravity Transcripts │
│  (send-message /     │      │   (.system_generated/   │
│   new-conversation)  │      │    transcript.jsonl)    │
└──────────────────────┘      └─────────────────────────┘
```

---

## 🚀 Quick Start

### 1. Clone the Repository
```bash
git clone https://github.com/PranavaM1102/antigravity-mobile-remote.git
cd antigravity-mobile-remote
```

### 2. Start the Server

**On Windows:**
Double-click `run.bat` or run:
```powershell
python server.py
```

**On Linux / macOS:**
```bash
chmod +x start.sh
./start.sh
```

### 3. Connect from Your Phone
When the server starts, it prints connection URLs and opens a QR code:
- **Outside home (4G/5G Mobile Data):** Scan `qr_internet.png` or open the Cloudflare HTTPS link printed in the console.
- **On Home Wi-Fi:** Open `http://<your-pc-ip>:8080`.
- **On Tailscale:** Open `http://<tailscale-ip>:8080`.

---

## 🤖 Telegram Bot Setup (Instant Notifications & System Status)

You can receive your latest tunnel link and system status directly in Telegram:

1. **Create your Bot**:
   - Open Telegram and search for [`@BotFather`](https://t.me/BotFather).
   - Send `/newbot`, name your bot (e.g. `MyAntigravityBot`), and get your **HTTP API Token**.
2. **Add Token**:
   - Open `telegram_config.json` and paste your token:
     ```json
     {
       "bot_token": "YOUR_BOT_TOKEN_HERE",
       "allowed_chat_ids": []
     }
     ```
   - *(Or set environment variable `TELEGRAM_BOT_TOKEN`)*
3. **Authorize Your Chat**:
   - Open your bot in Telegram and send:
     ```
     /start xxxx
     ```
     *(Use your current PIN)*
   - Your chat is instantly registered and authorized!

### Telegram Commands
| Command | Description |
| :--- | :--- |
| `/link` | Returns current active Cloudflare link, PIN, and QR code image |
| `/status` | Live PC health metrics (RAM, CPU, free disk space on C: and D:) |
| `/pin [code]` | Check current PIN or update it |
| `/cmd <cmd>` | Execute a PowerShell command on the workstation and view output |
| `/ask <prompt>` | Send a coding instruction directly to Antigravity |
| `/help` | Display command list |

---

## 📂 Repository Structure

```
antigravity-mobile-remote/
├── server.py              # Zero-dependency Python backend server
├── run.bat                # Windows 1-click launcher
├── start.sh               # Linux/macOS launcher
├── web/
│   ├── index.html         # Mobile web application UI
│   ├── style.css          # Glassmorphism dark mode styles
│   ├── app.js             # Client state, polling, voice recognition, shell
│   └── marked.min.js      # Self-contained Markdown parser
├── .gitignore             # Excludes binaries & temporary files
├── LICENSE                # MIT License
└── README.md              # Project documentation
```

---

## 🛠️ API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `GET /` | `GET` | Serves the mobile web interface |
| `GET /api/status` | `GET` | Returns online status, active session, and connection URLs |
| `GET /api/conversations` | `GET` | Lists all discovered Antigravity sessions |
| `GET /api/transcript?id=<id>` | `GET` | Fetches parsed messages and tool execution logs |
| `POST /api/send` | `POST` | Sends a message/command into an Antigravity conversation |
| `POST /api/new_conversation`| `POST` | Launches a new autonomous Antigravity conversation |
| `POST /api/exec_terminal` | `POST` | Runs a PowerShell / Shell command directly on the host |
| `GET /api/qr` | `GET` | Generates a quick QR code for instant mobile scanning |

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
