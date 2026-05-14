#!/bin/bash
# Antigravity Status Check Script

if pgrep -f "autonomic_engine.py" > /dev/null; then
    echo "[STATUS] Bot is RUNNING."
    echo "Last 10 lines of logs:"
    echo "--------------------------------------------------"
    tail -n 10 engine.log
    echo "--------------------------------------------------"
else
    echo "[STATUS] Bot is OFFLINE."
fi
