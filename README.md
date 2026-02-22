# Pay If You Like - VPN Automation Bot 🤖🔐

A full-stack Telegram bot solution for automating V2Ray/VLESS VPN service delivery. This system handles user management, key generation, payment verification via AI, and multi-server load balancing.

## 🚀 Features

- **Instant Free Trials:** Auto-generates 24-hour ephemeral keys for users.
- **AI Payment Verification:** Uses **Google Gemini 2.0 Flash** to scan and verify payment slips (KPay/Wave) automatically.
- **Admin Approval System:** Forwards unverified slips to an admin channel with inline "Approve/Decline" controls.
- **Multi-Server Support:** Manages multiple X-UI panels (Singapore, Japan) with smart load balancing.
- **VLESS-Reality Protocol:** Generates secure, censorship-resistant connection links.
- **24/7 Persistence:** Runs as a systemd service for maximum uptime.

## 🛠️ Tech Stack

- **Language:** Python 3.11+
- **Framework:** python-telegram-bot (Async)
- **AI/Vision:** Google Generative AI (Gemini)
- **VPN Backend:** X-UI Panel (V2Ray/Xray)
- **Deployment:** Linux (Systemd, Bash)

## 📂 Project Structure

```
├── admin_bot/          # Bot for Server Management & Admin Controls
│   ├── bot.py
│   └── requirements.txt
├── vpn_bot/            # Customer-Facing Bot
│   ├── bot.py          # Main logic (AI check, Key Gen)
│   ├── images/         # Guide assets
│   └── requirements.txt
└── README.md
```

## ⚙️ Configuration

Copy the example config and fill in your details:

```json
{
    "servers": [
        {
            "name": "Server 1",
            "panel_url": "https://your-panel-url:port/",
            "username": "admin",
            "password": "password",
            "inbound_id": 1,
            "flow_limit_gb": 100,
            "expire_days": 30
        }
    ],
    "bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
    "admin_ids": [12345678, 87654321],
    "gemini_api_key": "YOUR_GEMINI_API_KEY"
}
```

## 🚀 Deployment

1. Install dependencies:
   ```bash
   pip install -r vpn_bot/requirements.txt
   ```

2. Run the bot:
   ```bash
   python3 vpn_bot/bot.py
   ```

3. (Optional) Set up systemd service for background running.

## 🛡️ License

This project is for educational and portfolio purposes.
