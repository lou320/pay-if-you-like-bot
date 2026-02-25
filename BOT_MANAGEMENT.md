# Bot Management Guide

## Quick Start (After Getting Separate Tokens)

### Run Both Bots
```bash
cd ~/Downloads/payifyoulike/pay-if-you-like-bot
./run_bots.sh start
```

### Check Status
```bash
./run_bots.sh status
```

### Stop Both Bots
```bash
./run_bots.sh stop
```

### Watch Logs
```bash
./run_bots.sh logs
```

## The Token Issue

**Currently, both bots share the same Telegram token**, which means only ONE can run at a time. When you try to run both, you get a **Conflict** error.

### Solution: Create Two Bot Tokens

1. **Create a new Telegram bot:**
   - Go to [@BotFather](https://t.me/BotFather) on Telegram
   - Type `/newbot`
   - Give it a name (e.g., "PayIfYouLike VPN Bot")
   - Give it a username (e.g., "PayIfYouLikeVPNBot")
   - Copy the token you receive

2. **Update config.json:**
   ```bash
   nano ~/Downloads/payifyoulike/pay-if-you-like-bot/config.json
   ```
   
   Update these two fields:
   ```json
   {
     "bot_token": "CUSTOMER_BOT_TOKEN_HERE",
     "admin_bot_token": "ADMIN_BOT_TOKEN_HERE",
     ...
   }
   ```

3. **Restart the bots:**
   ```bash
   cd ~/Downloads/payifyoulike/pay-if-you-like-bot
   ./run_bots.sh restart
   ```

## Bot Architecture

### `admin_bot/bot.py` (Admin Control Panel)
- Reads `admin_bot_token` from config
- Restricted to admin users
- Commands: `/admin`
- Features: Generate keys, manage servers, check status

### `vpn_bot/bot.py` (Customer VPN Bot)
- Reads `bot_token` from config
- Public-facing for customers
- Commands: `/start`
- Features: Free trial, premium keys, quota check, setup guides

## Troubleshooting

### Both bots not responding?
Check if they're running:
```bash
./run_bots.sh status
```

### One bot crashes?
Check the logs:
```bash
tail -f admin_bot.log    # Admin bot logs
tail -f vpn_bot.log      # VPN bot logs
```

### Still getting Conflict errors?
Verify tokens in config:
```bash
./setup_tokens.sh
```

### Manual Stop (if needed)
```bash
pkill -f "admin_bot/bot.py"
pkill -f "vpn_bot/bot.py"
```

### Manual Start (for debugging)
```bash
# Admin bot
cd admin_bot && python3 -u bot.py

# VPN bot (in another terminal)
cd vpn_bot && python3 -u bot.py
```

## Script Commands Reference

| Command | Action |
|---------|--------|
| `./run_bots.sh start` | Start both bots |
| `./run_bots.sh stop` | Stop both bots |
| `./run_bots.sh restart` | Restart both bots |
| `./run_bots.sh status` | Check bot status |
| `./run_bots.sh logs` | Tail both logs |
| `./run_bots.sh help` | Show help |

## Separate Bots Advantage

With two bots:
- ✅ Admin can manage servers while customers use the bot
- ✅ Better security (admin bot is restricted)
- ✅ Scalable architecture
- ✅ Can restart one without affecting the other
