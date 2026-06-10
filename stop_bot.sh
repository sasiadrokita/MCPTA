#!/bin/bash
# Antigravity Stop Script
# Gracefully stops the bot engine and dashboard

APP_DIR="/home/mateusz/MCPTA"

echo "[*] Stopping Antigravity..."

# 1. Stop the bot engine
if pgrep -f "autonomic_engine.py" > /dev/null; then
    echo "[*] Stopping engine..."
    pkill -f "autonomic_engine.py"
    sleep 2
    # Force kill if still alive
    if pgrep -f "autonomic_engine.py" > /dev/null; then
        echo "[!] Engine didn't stop gracefully. Force killing..."
        pkill -9 -f "autonomic_engine.py"
    fi
    echo "[OK] Engine stopped."
else
    echo "[*] Engine was not running."
fi

# 2. Stop the dashboard
if pgrep -f "dashboard.py" > /dev/null; then
    echo "[*] Stopping dashboard..."
    pkill -f "dashboard.py"
    sleep 1
    if pgrep -f "dashboard.py" > /dev/null; then
        pkill -9 -f "dashboard.py"
    fi
    echo "[OK] Dashboard stopped."
else
    echo "[*] Dashboard was not running."
fi

echo "[OK] All systems stopped."
