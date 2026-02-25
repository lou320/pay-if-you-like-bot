#!/bin/bash

# Bot Configuration Setup Guide
# This script helps you set up separate tokens for both bots

echo "╔════════════════════════════════════════════════════════════╗"
echo "║   Bot Token Configuration Check & Setup Guide             ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

CONFIG_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.json"

echo "📝 Current Configuration: $CONFIG_FILE"
echo ""

# Check current tokens
BOT_TOKEN=$(jq -r '.bot_token' "$CONFIG_FILE")
ADMIN_BOT_TOKEN=$(jq -r '.admin_bot_token' "$CONFIG_FILE")

echo "Current Tokens:"
echo "  bot_token:       ${BOT_TOKEN:0:20}***"
echo "  admin_bot_token: ${ADMIN_BOT_TOKEN:0:20}***"
echo ""

if [ "$BOT_TOKEN" == "$ADMIN_BOT_TOKEN" ]; then
    echo "⚠️  WARNING: Both tokens are identical!"
    echo "    Only ONE bot can run with the same token at a time."
    echo ""
    echo "🔧 Solution: You need TWO separate Telegram bot tokens:"
    echo ""
    echo "1. Create a new bot on Telegram via @BotFather:"
    echo "   - Message @BotFather on Telegram"
    echo "   - Type: /newbot"
    echo "   - Follow the prompts to create a new bot"
    echo "   - Copy the new token"
    echo ""
    echo "2. Update config.json with the new token:"
    echo "   - Set 'admin_bot_token' to your NEW bot token"
    echo "   - Keep 'bot_token' as the CUSTOMER bot token"
    echo ""
    echo "3. Example config structure:"
    cat << 'EOF'
{
  "bot_token": "123456789:ABCdefGHIjklmnoPQRstuvWXYZabcdefgh",  // Customer VPN Bot
  "admin_bot_token": "987654321:XYZabcdefGHIjklmnoPQRstuvWXYZ123", // Admin Control Bot
  ...
}
EOF
    echo ""
    echo "4. After updating, restart both bots:"
    echo "   cd $(dirname "$CONFIG_FILE")"
    echo "   ./run_bots.sh restart"
else
    echo "✅ Tokens are different - bots can run simultaneously!"
fi

echo ""
echo "📖 Additional Resources:"
echo "  - Telegram BotFather: https://t.me/BotFather"
echo "  - python-telegram-bot docs: https://python-telegram-bot.readthedocs.io"
echo ""
