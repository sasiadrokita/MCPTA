"""
Circuit Breaker — Antigravity AI
===================================
Tracks consecutive losses per (symbol, side) pair.
After MAX_CONSECUTIVE_LOSSES consecutive SL hits on the same symbol/side,
trading on that pair is blocked for COOLDOWN_HOURS.

A WIN resets the consecutive loss counter.
State is persisted in Redis (with JSON file fallback) to survive restarts.
"""

import json
import os
import time
import threading
from datetime import datetime, timezone

# --- CONFIGURATION ---
MAX_CONSECUTIVE_LOSSES = 3      # block after this many consecutive losses
COOLDOWN_HOURS = 4              # hours to block the pair/side after trigger
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "circuit_breaker_state.json")

_lock = threading.Lock()
_state = {}   # { "SOLUSDT_SHORT": {"consecutive_losses": 2, "blocked_until": 0.0, "total_triggers": 1} }

# Try Redis
try:
    import redis as redis_lib
    _redis = redis_lib.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    _redis.ping()
    _REDIS_OK = True
except Exception:
    _REDIS_OK = False

_CB_REDIS_KEY = "antigravity:circuit_breaker"


def _load_state():
    global _state
    # Try Redis first
    if _REDIS_OK:
        try:
            raw = _redis.get(_CB_REDIS_KEY)
            if raw:
                _state = json.loads(raw)
                return
        except Exception:
            pass
    # Fallback to file
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                _state = json.load(f)
            return
        except Exception:
            pass
    _state = {}


def _save_state():
    if _REDIS_OK:
        try:
            _redis.set(_CB_REDIS_KEY, json.dumps(_state))
            return
        except Exception:
            pass
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(_state, f, indent=2)
    except Exception as e:
        print(f"[CIRCUIT BREAKER] State save error: {e}")


def _key(symbol: str, side: str) -> str:
    return f"{symbol.upper()}_{side.upper()}"


def is_blocked(symbol: str, side: str) -> tuple[bool, str]:
    """
    Returns (blocked: bool, reason: str).
    Call this before opening any new position.
    """
    with _lock:
        _load_state()
        k = _key(symbol, side)
        entry = _state.get(k, {})
        blocked_until = entry.get("blocked_until", 0.0)
        now = time.time()

        if blocked_until > now:
            remaining_min = int((blocked_until - now) / 60)
            consecutive = entry.get("consecutive_losses", 0)
            reason = (
                f"CIRCUIT BREAKER ACTIVE: {symbol} {side} — "
                f"{consecutive} consecutive losses. "
                f"Blocked for {remaining_min} more minutes."
            )
            return True, reason

        return False, ""


def record_loss(symbol: str, side: str) -> int:
    """
    Register a loss. Returns the current consecutive loss count.
    Triggers a block if MAX_CONSECUTIVE_LOSSES is reached.
    """
    with _lock:
        _load_state()
        k = _key(symbol, side)
        entry = _state.setdefault(k, {"consecutive_losses": 0, "blocked_until": 0.0, "total_triggers": 0})

        entry["consecutive_losses"] += 1
        consecutive = entry["consecutive_losses"]
        entry["last_loss_ts"] = time.time()

        if consecutive >= MAX_CONSECUTIVE_LOSSES:
            blocked_until = time.time() + (COOLDOWN_HOURS * 3600)
            entry["blocked_until"] = blocked_until
            entry["total_triggers"] = entry.get("total_triggers", 0) + 1
            # Don't reset counter — let it keep counting during cooldown
            ts = datetime.fromtimestamp(blocked_until, tz=timezone.utc).strftime('%H:%M UTC')
            print(
                f"[CIRCUIT BREAKER] 🔴 TRIGGERED: {symbol} {side} — "
                f"{consecutive} consecutive losses. BLOCKED until {ts} "
                f"({COOLDOWN_HOURS}h cooldown). Total triggers: {entry['total_triggers']}",
                flush=True
            )
        else:
            print(
                f"[CIRCUIT BREAKER] ⚠️  {symbol} {side} — "
                f"Loss #{consecutive}/{MAX_CONSECUTIVE_LOSSES}. "
                f"{'One more loss triggers cooldown!' if consecutive == MAX_CONSECUTIVE_LOSSES - 1 else ''}",
                flush=True
            )

        _save_state()
        return consecutive


def record_win(symbol: str, side: str):
    """
    Register a win — resets the consecutive loss counter for this pair/side.
    Does NOT lift an active cooldown block early.
    """
    with _lock:
        _load_state()
        k = _key(symbol, side)
        entry = _state.get(k, {})
        prev_losses = entry.get("consecutive_losses", 0)

        if k in _state:
            _state[k]["consecutive_losses"] = 0
            _state[k]["last_win_ts"] = time.time()

        _save_state()

        if prev_losses > 0:
            print(
                f"[CIRCUIT BREAKER] ✅ WIN on {symbol} {side} — "
                f"Consecutive loss streak reset (was {prev_losses}).",
                flush=True
            )


def get_status() -> dict:
    """Returns the full circuit breaker state for monitoring/reporting."""
    with _lock:
        _load_state()
        now = time.time()
        status = {}
        for k, entry in _state.items():
            blocked_until = entry.get("blocked_until", 0.0)
            status[k] = {
                "consecutive_losses": entry.get("consecutive_losses", 0),
                "is_blocked": blocked_until > now,
                "blocked_until_readable": (
                    datetime.fromtimestamp(blocked_until, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
                    if blocked_until > now else "NOT BLOCKED"
                ),
                "total_triggers": entry.get("total_triggers", 0),
            }
        return status


def force_reset(symbol: str, side: str):
    """Manually reset a circuit breaker block (for debugging/admin use)."""
    with _lock:
        _load_state()
        k = _key(symbol, side)
        if k in _state:
            _state[k]["consecutive_losses"] = 0
            _state[k]["blocked_until"] = 0.0
            _save_state()
            print(f"[CIRCUIT BREAKER] 🔓 MANUAL RESET: {symbol} {side} unblocked.", flush=True)


# Load state on import
_load_state()
print(
    f"[CIRCUIT BREAKER] Loaded. Config: MAX_LOSSES={MAX_CONSECUTIVE_LOSSES}, "
    f"COOLDOWN={COOLDOWN_HOURS}h. "
    f"Active blocks: {sum(1 for e in _state.values() if e.get('blocked_until', 0) > time.time())}",
    flush=True
)
