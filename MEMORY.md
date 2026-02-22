# MEMORY.md - Long Term Context

## User Profile: Theo Mon
- **Role:** Entrepreneur / Tech Enthusiast (Myanmar).
- **Business:** "Pay If You Like" (VPN Service).
- **Interests:** Pentesting, AI (Deepfakes/LoRA), Spaceflight Simulator, Polymarket betting.
- **Language:** Burmese (for customers), English (for dev).

## Projects & Infrastructure

### 1. VPN Business (Pay If You Like)
- **Bots:**
  - **Customer Bot:** `@PayIfYouLikeBot` (Auto-sells keys, Free Trials, Gemini OCR for slips).
  - **Admin Bot:** `@PayIfYouLikeAdminBot` (Server management, Key gen).
  - **Path:** `/root/.openclaw/workspace/vpn_bot/` and `admin_bot/`.
- **Servers:**
  - **Server 1 (Singapore):** `157.245.58.241` (X-UI Panel).
  - **Server 2 (Japan):** `34.87.46.97` (X-UI Panel).
- **Tech Stack:**
  - **Protocol:** VLESS-Reality & VLESS-WS (Cloudflare).
  - **Domain:** `scammerdb.website` (Cloudflare Proxied).
  - **Payment:** KPay (`09799881201`).

### 2. Other Experiments
- **Voice Chat:** Built a secure voice link (`https://rook.scammerdb.website:8443`) using Termux as a client.
- **Polymarket:** Created a news-based betting bot script.
- **Spaceflight Simulator:** Created custom BP-edited blueprints (Infinite Fuel).
