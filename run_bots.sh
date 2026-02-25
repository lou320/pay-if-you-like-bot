#!/bin/bash

# Dual Bot Manager Script
# Manages both admin_bot and vpn_bot instances
# Usage: ./run_bots.sh [start|stop|restart|status]

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADMIN_BOT_DIR="$REPO_ROOT/admin_bot"
VPN_BOT_DIR="$REPO_ROOT/vpn_bot"
VENV_BIN="$REPO_ROOT/venv/bin/python3"

ADMIN_BOT_LOG="$REPO_ROOT/admin_bot.log"
VPN_BOT_LOG="$REPO_ROOT/vpn_bot.log"
ADMIN_BOT_PID_FILE="$REPO_ROOT/.admin_bot.pid"
VPN_BOT_PID_FILE="$REPO_ROOT/.vpn_bot.pid"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_info() {
    echo -e "${YELLOW}[i]${NC} $1"
}

start_bots() {
    print_info "Starting both bots..."
    
    # Kill any existing processes
    pkill -f "admin_bot/bot.py" || true
    pkill -f "vpn_bot/bot.py" || true
    sleep 1
    
    # Start Admin Bot
    print_info "Starting Admin Bot..."
    cd "$ADMIN_BOT_DIR"
    nohup $VENV_BIN -u bot.py > "$ADMIN_BOT_LOG" 2>&1 &
    ADMIN_PID=$!
    echo $ADMIN_PID > "$ADMIN_BOT_PID_FILE"
    print_status "Admin Bot started (PID: $ADMIN_PID)"
    print_info "Log: $ADMIN_BOT_LOG"
    
    sleep 2
    
    # Start VPN Bot
    print_info "Starting VPN Bot..."
    cd "$VPN_BOT_DIR"
    nohup $VENV_BIN -u bot.py > "$VPN_BOT_LOG" 2>&1 &
    VPN_PID=$!
    echo $VPN_PID > "$VPN_BOT_PID_FILE"
    print_status "VPN Bot started (PID: $VPN_PID)"
    print_info "Log: $VPN_BOT_LOG"
    
    sleep 2
    
    # Verify both are running
    if ps -p $ADMIN_PID > /dev/null; then
        print_status "Admin Bot is running"
    else
        print_error "Admin Bot failed to start"
        return 1
    fi
    
    if ps -p $VPN_PID > /dev/null; then
        print_status "VPN Bot is running"
    else
        print_error "VPN Bot failed to start"
        return 1
    fi
    
    print_status "Both bots are now running!"
}

stop_bots() {
    print_info "Stopping both bots..."
    
    if [ -f "$ADMIN_BOT_PID_FILE" ]; then
        ADMIN_PID=$(cat "$ADMIN_BOT_PID_FILE")
        if ps -p $ADMIN_PID > /dev/null 2>&1; then
            kill $ADMIN_PID 2>/dev/null || true
            print_status "Admin Bot stopped"
        fi
        rm -f "$ADMIN_BOT_PID_FILE"
    fi
    
    if [ -f "$VPN_BOT_PID_FILE" ]; then
        VPN_PID=$(cat "$VPN_BOT_PID_FILE")
        if ps -p $VPN_PID > /dev/null 2>&1; then
            kill $VPN_PID 2>/dev/null || true
            print_status "VPN Bot stopped"
        fi
        rm -f "$VPN_BOT_PID_FILE"
    fi
    
    # Fallback: kill all matching processes
    pkill -f "admin_bot/bot.py" || true
    pkill -f "vpn_bot/bot.py" || true
    
    print_status "All bots stopped"
}

status_bots() {
    print_info "Checking bot status..."
    
    ADMIN_RUNNING=0
    VPN_RUNNING=0
    
    if [ -f "$ADMIN_BOT_PID_FILE" ]; then
        ADMIN_PID=$(cat "$ADMIN_BOT_PID_FILE")
        if ps -p $ADMIN_PID > /dev/null 2>&1; then
            print_status "Admin Bot is running (PID: $ADMIN_PID)"
            ADMIN_RUNNING=1
        else
            print_error "Admin Bot is NOT running (stale PID: $ADMIN_PID)"
        fi
    else
        print_error "Admin Bot is NOT running (no PID file)"
    fi
    
    if [ -f "$VPN_BOT_PID_FILE" ]; then
        VPN_PID=$(cat "$VPN_BOT_PID_FILE")
        if ps -p $VPN_PID > /dev/null 2>&1; then
            print_status "VPN Bot is running (PID: $VPN_PID)"
            VPN_RUNNING=1
        else
            print_error "VPN Bot is NOT running (stale PID: $VPN_PID)"
        fi
    else
        print_error "VPN Bot is NOT running (no PID file)"
    fi
    
    echo ""
    if [ $ADMIN_RUNNING -eq 1 ] && [ $VPN_RUNNING -eq 1 ]; then
        print_status "Both bots are running ✓"
        return 0
    else
        print_error "One or more bots are not running ✗"
        return 1
    fi
}

tail_logs() {
    print_info "Tailing logs (Admin | VPN)..."
    echo ""
    paste -d '|' <(tail -f "$ADMIN_BOT_LOG" | sed 's/^/[ADMIN] /') \
                  <(tail -f "$VPN_BOT_LOG" | sed 's/^/[VPN]   /')
}

show_help() {
    cat << EOF
╔════════════════════════════════════════════════════════════╗
║        Pay If You Like - Dual Bot Manager Script           ║
╚════════════════════════════════════════════════════════════╝

Usage: ./run_bots.sh [COMMAND]

Commands:
  start       Start both bots (kills any existing instances)
  stop        Stop both bots
  restart     Restart both bots (equivalent to: stop, then start)
  status      Check status of both bots
  logs        Tail both bot logs in real-time
  help        Show this help message

Examples:
  ./run_bots.sh start              # Start both bots
  ./run_bots.sh restart            # Restart both bots
  ./run_bots.sh status             # Check if both bots running
  ./run_bots.sh logs               # Watch logs live

Log Files:
  Admin Bot: $ADMIN_BOT_LOG
  VPN Bot:   $VPN_BOT_LOG

Quick Debug:
  tail -f $ADMIN_BOT_LOG   # Watch Admin Bot logs
  tail -f $VPN_BOT_LOG     # Watch VPN Bot logs

EOF
}

# Main Command Handler
COMMAND=${1:-help}

case "$COMMAND" in
    start)
        start_bots
        ;;
    stop)
        stop_bots
        ;;
    restart)
        stop_bots
        sleep 1
        start_bots
        ;;
    status)
        status_bots
        ;;
    logs)
        tail_logs
        ;;
    help)
        show_help
        ;;
    *)
        print_error "Unknown command: $COMMAND"
        show_help
        exit 1
        ;;
esac
