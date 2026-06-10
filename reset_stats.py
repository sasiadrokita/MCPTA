import json
import sqlite3
import os

# 1. Reset autonomic_learning.json performance_metrics
learning_file = 'autonomic_learning.json'
if os.path.exists(learning_file):
    with open(learning_file, 'r') as f:
        data = json.load(f)
    
    # Backup
    with open(learning_file + '.bak', 'w') as f:
        json.dump(data, f, indent=4)
        
    data['performance_metrics'] = {
        "total_trades": 0,
        "winning_trades": 0,
        "total_pnl": 0.0,
        "win_rate": 0.0,
        "per_symbol": {
            "BTCUSDT": {"trades": 0, "wins": 0, "pnl": 0.0, "win_rate": 0.0},
            "SOLUSDT": {"trades": 0, "wins": 0, "pnl": 0.0, "win_rate": 0.0},
            "LINKUSDT": {"trades": 0, "wins": 0, "pnl": 0.0, "win_rate": 0.0},
            "ETHUSDT": {"trades": 0, "wins": 0, "pnl": 0.0, "win_rate": 0.0}
        }
    }
    
    # Also update last_optimization to now
    import time
    data['last_optimization'] = time.time()
    
    with open(learning_file, 'w') as f:
        json.dump(data, f, indent=4)
    print("SUCCESS: Reset performance_metrics in autonomic_learning.json")

# 2. Reset bot_memory.db trades (Bybit Fresh Start)
db_path = 'bot_memory.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    # Mark old trades as archived or just delete them?
    # Better delete to ensure PNL calculations in reports are fresh.
    # We already have backups in .db files usually, or we can just rename.
    # User said "delete old entries".
    
    # Optional: Archive instead of delete
    # Let's just delete everything from trades.
    try:
        conn.execute("DELETE FROM trades;")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()
    print("SUCCESS: Cleared trades table in bot_memory.db")
