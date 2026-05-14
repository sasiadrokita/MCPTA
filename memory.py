#!/usr/bin/env python3
"""
BotMemory — Persistent memory layer for the Antigravity system.
Version: v21.13.0

Two storage types:
  1. SQLite  — Persistent storage for decisions, trades, and lessons (disk)
  2. Redis   — Fast cache for current state (RAM, TTL 24h)
"""

import sqlite3
import json
import os
import time
from datetime import datetime, timezone

# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, 'bot_memory.db')

# Redis — Optional, graceful failover if unavailable
try:
    import redis
    _redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    _redis_client.ping()
    REDIS_OK = True
except Exception:
    _redis_client = None
    REDIS_OK = False

# ──────────────────────────────────────────────────────────────────────────────
def _get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Creates tables if they do not exist."""
    with _get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS decisions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            symbol      TEXT    NOT NULL,
            action      TEXT    NOT NULL,
            reasoning   TEXT,
            context     TEXT,
            nexus_score REAL,
            confidence  REAL
        );

        CREATE TABLE IF NOT EXISTS trades (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            open_ts        TEXT    NOT NULL,
            close_ts        TEXT,
            symbol         TEXT    NOT NULL,
            side           TEXT    NOT NULL,
            entry_price    REAL,
            exit_price     REAL,
            qty            REAL,
            pnl            REAL,
            close_reason   TEXT,
            context        TEXT
        );

        CREATE TABLE IF NOT EXISTS lessons (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     TEXT    NOT NULL,
            symbol        TEXT    NOT NULL,
            rule_if       TEXT    NOT NULL,
            rule_then     TEXT    NOT NULL,
            rule_because  TEXT,
            source_trade  INTEGER,
            FOREIGN KEY (source_trade) REFERENCES trades(id)
        );

        CREATE INDEX IF NOT EXISTS idx_decisions_symbol ON decisions(symbol);
        CREATE INDEX IF NOT EXISTS idx_trades_symbol    ON trades(symbol);
        CREATE INDEX IF NOT EXISTS idx_lessons_symbol   ON lessons(symbol);
        """)
    print(f"[MEMORY] SQLite ready: {os.path.abspath(DB_PATH)}")

# ──────────────────────────────────────────────────────────────────────────────
# DECISIONS
# ──────────────────────────────────────────────────────────────────────────────

def save_decision(symbol: str, action: str, reasoning: str = None,
                  context: dict = None, nexus_score: float = None,
                  confidence: float = None):
    """Saves a single AI decision to SQLite."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ctx_str = json.dumps(context, ensure_ascii=False) if context else None
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO decisions (timestamp, symbol, action, reasoning, context, nexus_score, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, symbol, action, reasoning, ctx_str, nexus_score, confidence)
            )
    except Exception as e:
        print(f"[MEMORY] save_decision error: {e}")

# ──────────────────────────────────────────────────────────────────────────────
# TRADES
# ──────────────────────────────────────────────────────────────────────────────

def save_trade_open(symbol: str, side: str, entry_price: float,
                    qty: float, context: dict = None) -> int:
    """Opens a new trade entry and returns its ID."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ctx_str = json.dumps(context, ensure_ascii=False) if context else None
    try:
        with _get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO trades (open_ts, symbol, side, entry_price, qty, context) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ts, symbol, side, entry_price, qty, ctx_str)
            )
            return cur.lastrowid
    except Exception as e:
        print(f"[MEMORY] save_trade_open error: {e}")
        return -1

def save_trade_close(symbol: str, exit_price: float, pnl: float,
                     close_reason: str = None, trade_id: int = None):
    """Closes an open trade — updates exit_price, pnl, and close_ts."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with _get_conn() as conn:
            if trade_id:
                conn.execute(
                    "UPDATE trades SET close_ts=?, exit_price=?, pnl=?, close_reason=? WHERE id=?",
                    (ts, exit_price, pnl, close_reason, trade_id)
                )
            else:
                # fallback: find the latest open trade for the symbol
                conn.execute(
                    "UPDATE trades SET close_ts=?, exit_price=?, pnl=?, close_reason=? "
                    "WHERE symbol=? AND close_ts IS NULL ORDER BY id DESC LIMIT 1",
                    (ts, exit_price, pnl, close_reason, symbol)
                )
    except Exception as e:
        print(f"[MEMORY] save_trade_close error: {e}")

def get_trade_by_id(trade_id: int) -> dict:
    """Fetches full trade data from SQLite based on ID."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM trades WHERE id=?", (trade_id,)
            ).fetchone()
            return dict(row) if row else None
    except Exception as e:
        print(f"[MEMORY] get_trade_by_id error: {e}")
        return None

def get_open_trades_from_db() -> list[dict]:
    """Fetches trades that are not closed according to the database (close_ts IS NULL)."""
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE close_ts IS NULL"
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[MEMORY] get_open_trades_from_db error: {e}")
        return []

# ──────────────────────────────────────────────────────────────────────────────
# LESSONS
# ──────────────────────────────────────────────────────────────────────────────

def save_lesson(symbol: str, rule_if: str, rule_then: str,
                rule_because: str = None, source_trade: int = None):
    """Saves a lesson extracted by AI."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO lessons (timestamp, symbol, rule_if, rule_then, rule_because, source_trade) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ts, symbol, rule_if, rule_then, rule_because, source_trade)
            )
    except Exception as e:
        print(f"[MEMORY] save_lesson error: {e}")

def get_recent_lessons(symbol: str, limit: int = 5) -> list[dict]:
    """Returns recent lessons for a symbol to inject into the prompt."""
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT rule_if, rule_then, rule_because FROM lessons "
                "WHERE symbol=? ORDER BY id DESC LIMIT ?",
                (symbol, limit)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[MEMORY] get_recent_lessons error: {e}")
        return []

# ──────────────────────────────────────────────────────────────────────────────
# REDIS CACHE
# ──────────────────────────────────────────────────────────────────────────────

def redis_set(key: str, value, ttl: int = 86400):
    """Saves value to Redis with TTL (default 24h)."""
    if not REDIS_OK:
        return
    try:
        _redis_client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
    except Exception as e:
        print(f"[MEMORY/REDIS] set error {key}: {e}")

def redis_get(key: str):
    """Reads value from Redis. Returns None if key does not exist."""
    if not REDIS_OK:
        return None
    try:
        val = _redis_client.get(key)
        return json.loads(val) if val else None
    except Exception as e:
        print(f"[MEMORY/REDIS] get error {key}: {e}")
        return None

def update_market_state_cache(symbol: str, nexus_score: float,
                                macro_bias: str, last_action: str):
    """Updates the fast market state cache for a symbol."""
    redis_set(f"market:{symbol}", {
        "nexus_score": nexus_score,
        "macro_bias": macro_bias,
        "last_action": last_action,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    })

# ──────────────────────────────────────────────────────────────────────────────
# Initialization on import
# ──────────────────────────────────────────────────────────────────────────────
init_db()
print(f"[MEMORY] Redis: {'OK ✓' if REDIS_OK else 'Unavailable (SQLite only)'}")
