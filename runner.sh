#!/bin/bash
# Antigravity Engine Runner — single-instance guardian
# Run as: bash /home/mateusz/MCPTA/runner.sh

LOCKFILE="/tmp/antigravity.lock"
PIDFILE="/tmp/antigravity.pid"
LOGFILE="/home/mateusz/MCPTA/engine.log"
ENGINE="/home/mateusz/MCPTA/autonomic_engine.py"
VENV="/home/mateusz/MCPTA/venv/bin/python3"

# If process already exists — do not start another
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[RUNNER] Engine already running (PID: $OLD_PID). Exiting."
        exit 0
    fi
fi

# Kill any previous processes
pkill -f autonomic_engine.py 2>/dev/null
sleep 1

# Start fresh instance
echo "[RUNNER] Starting Antigravity Engine..."
cd /home/mateusz/MCPTA
nohup "$VENV" "$ENGINE" > "$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"
echo "[RUNNER] Engine started with PID: $(cat $PIDFILE)"
