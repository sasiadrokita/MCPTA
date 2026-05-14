#!/bin/bash

# Antigravity Startup Script (Managed via version.py)

APP_DIR="/home/mateusz/MCPTA"
cd $APP_DIR

# 1. Check if bot is already running
if pgrep -f "autonomic_engine.py" > /dev/null; then
    echo "[!] Antigravity is already running. Use 'pkill -f autonomic_engine.py' if you want to restart it."
    exit 1
fi

# 1.5 Get version from version.py
VERSION=$(grep "^VERSION =" version.py | cut -d'"' -f2)
CODENAME=$(grep "^CODENAME =" version.py | cut -d'"' -f2)

# 2. Start bot in background using VENV
echo "[+] Starting Antigravity $VERSION ($CODENAME) in background (VENV)..."
nohup ./venv/bin/python autonomic_engine.py > engine.log 2>&1 &

# 3. Start dashboard in background
echo "[+] Starting Dashboard..."
nohup ./venv/bin/python dashboard.py > /tmp/dashboard.log 2>&1 &

# 4. Show result
sleep 2
BOT_OK=0
DASH_OK=0

if pgrep -f "autonomic_engine.py" > /dev/null; then BOT_OK=1; fi
if pgrep -f "dashboard.py" > /dev/null; then DASH_OK=1; fi

if [ $BOT_OK -eq 1 ] && [ $DASH_OK -eq 1 ]; then
    echo "[OK] All systems started successfully."
    echo "  - Bot: engine.log"
    echo "  - Dashboard: http://localhost:5000"
    echo "You can now safely close this terminal."
else
    echo "[ERROR] Some systems failed to start."
    [ $BOT_OK -eq 0 ] && echo "  - Bot: FAILED (check engine.log)"
    [ $DASH_OK -eq 0 ] && echo "  - Dashboard: FAILED (check /tmp/dashboard.log)"
fi
