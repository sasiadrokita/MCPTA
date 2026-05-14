#!/usr/bin/env python3
"""
One-time cleanup script: Sync SQLite database with Binance history.
Does NOT use Gemini API — only Binance REST + SQLite.
"""
import sqlite3
import json
import os
import sys
import time

# Add project path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from autonomic_engine import binance_request

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot_memory.db')

def get_binance_open_symbols():
    """Fetches a list of symbols with actually open positions on the exchange."""
    positions = binance_request('/fapi/v2/positionRisk')
    active = set()
    if isinstance(positions, list):
        for p in positions:
            if abs(float(p.get('positionAmt', 0))) > 0:
                active.add(p['symbol'])
    return active

def recover_pnl_from_history(symbol, entry_price, side, qty, open_ts):
    """Attempts to recover PnL from Binance trade history for a given symbol."""
    trades = binance_request('/fapi/v1/userTrades', f"symbol={symbol}&limit=50", silent=True)
    if not isinstance(trades, list) or len(trades) == 0:
        return 0.0, 0.0

    # Look for closing trades - those with realizedPnl != 0
    total_pnl = 0.0
    last_price = 0.0
    
    for t in trades:
        rpnl = float(t.get('realizedPnl', 0))
        if rpnl != 0:
            total_pnl += rpnl
            last_price = float(t.get('price', 0))
    
    return total_pnl, last_price

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. Fetch actually open positions from Binance
    print("[SYNC] Fetching active positions from Binance...", flush=True)
    binance_open = get_binance_open_symbols()
    print(f"[SYNC] Binance has open positions for: {binance_open or 'NONE'}")

    # 2. Find "ghosts" in the DB (open in SQLite, closed on exchange)
    cur.execute("SELECT * FROM trades WHERE close_ts IS NULL")
    db_open = cur.fetchall()
    
    ghosts = []
    still_open = []
    for t in db_open:
        if t['symbol'] not in binance_open:
            ghosts.append(dict(t))
        else:
            still_open.append(dict(t))

    print(f"\n[SYNC] Open in database: {len(db_open)}")
    print(f"[SYNC] Ghosts (to be closed): {len(ghosts)}")
    print(f"[SYNC] Actually open: {len(still_open)}")

    # 3. Close ghosts
    closed_count = 0
    for g in ghosts:
        tid = g['id']
        sym = g['symbol']
        print(f"\n  Closing ghost #{tid} ({sym} {g['side']} @ {g['entry_price']})...", end=" ")
        
        cur.execute(
            "UPDATE trades SET close_ts = datetime('now'), exit_price = 0, pnl = 0, close_reason = 'GHOST_CLEANUP' WHERE id = ?",
            (tid,)
        )
        closed_count += 1
        print("OK")
        time.sleep(0.1)  # Brief pause

    # 4. Fix PnL = 0 in closed trades (fetch from Binance)
    cur.execute("SELECT * FROM trades WHERE close_ts IS NOT NULL AND pnl = 0 AND exit_price = 0")
    zero_pnl = cur.fetchall()
    print(f"\n[SYNC] Trades with PnL=0 to fix: {len(zero_pnl)}")

    # Group by symbol to avoid API bombardment
    symbols_to_fix = {}
    for t in zero_pnl:
        sym = t['symbol']
        if sym not in symbols_to_fix:
            symbols_to_fix[sym] = []
        symbols_to_fix[sym].append(dict(t))

    fixed = 0
    for sym, trades_list in symbols_to_fix.items():
        print(f"\n  Fetching history for {sym}...", end=" ", flush=True)
        all_trades = binance_request('/fapi/v1/userTrades', f"symbol={sym}&limit=100", silent=True)
        time.sleep(0.3)  # Rate limit
        
        if not isinstance(all_trades, list):
            print("ERROR - skipping")
            continue
        
        # Calculate total realizedPnl for this symbol
        total_rpnl = sum(float(t.get('realizedPnl', 0)) for t in all_trades)
        print(f"Total realizedPnl from history: {total_rpnl:.4f} USDT")
        
        # Distribute proportionally (simplified: split equally)
        if len(trades_list) > 0 and total_rpnl != 0:
            share = round(total_rpnl / len(trades_list), 4)
            for t in trades_list:
                cur.execute("UPDATE trades SET pnl = ? WHERE id = ?", (share, t['id']))
                fixed += 1

    conn.commit()

    # 5. Final report
    print(f"\n{'='*60}")
    print(f"[SYNC] SUMMARY:")
    print(f"  Ghosts closed: {closed_count}")
    print(f"  PnL fixed:      {fixed}")
    
    # New statistics
    row = conn.execute(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins, "
        "SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses, "
        "ROUND(SUM(pnl), 4) as total_pnl "
        "FROM trades WHERE close_ts IS NOT NULL"
    ).fetchone()
    print(f"\n  ALL TIME STATS: {dict(row)}")
    
    open_count = conn.execute("SELECT COUNT(*) FROM trades WHERE close_ts IS NULL").fetchone()[0]
    print(f"  Remaining open: {open_count}")
    print(f"{'='*60}")
    
    conn.close()

if __name__ == '__main__':
    main()
