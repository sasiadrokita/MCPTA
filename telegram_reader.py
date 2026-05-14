"""
Antigravity v12.0 – Telegram Public Channel Scraper
Reads the public channel t.me/s/YOUR_CHANNEL_ID via HTTP (no login required).
Parses messages and saves signals to the `channel_signals` buffer.
"""
import asyncio
import json
import os
import re
import threading
import time
import datetime
import urllib.request as request
import ssl
import html

# SSL context (same as in autonomic_engine)
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHANNEL_URL = os.getenv("TG_CHANNEL_URL", "https://t.me/s/YOUR_CHANNEL_ID")
TG_JSON_FILE = os.path.join(BASE_DIR, 'tg_signals.json')
POLL_INTERVAL = 300  # Every 5 minutes

def get_channel_id_from_url(url: str) -> str:
    """Extracts the channel name from the t.me/s/NAME URL."""
    return url.split('/')[-1]

CHANNEL_ID = get_channel_id_from_url(CHANNEL_URL)

# Shared buffer – imported by autonomic_engine.py
channel_signals = []
_signals_lock = threading.Lock()
_last_seen_ids = set()

# Symbol Mapping: aliases -> SYMBOL
SYMBOL_MAP = {
    "btc": "BTCUSDT", "bitcoin": "BTCUSDT",
    "eth": "ETHUSDT", "ethereum": "ETHUSDT",
    "sol": "SOLUSDT", "solana": "SOLUSDT",
    "link": "LINKUSDT", "chainlink": "LINKUSDT",
}

BULL_WORDS = {"long", "buy", "bull", "bullish", "pump", "growth", "upward", "green"}
BEAR_WORDS = {"short", "sell", "bear", "bearish", "dump", "down", "red", "drop", "correction"}

def fetch_channel_html() -> str:
    """Fetches the current HTML page of the channel."""
    try:
        req = request.Request(
            CHANNEL_URL,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AntigravityBot/12.0)"}
        )
        with request.urlopen(req, timeout=15, context=ctx) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[TG READER] Channel fetch error: {e}", flush=True)
        return ""

def parse_html_messages(html_content: str) -> list:
    """Extracts messages from raw t.me/s/ HTML."""
    messages = []
    # Search for message blocks (dynamic for channel ID)
    pattern = re.findall(
        rf'data-post="{CHANNEL_ID}/(\d+)".*?<div[^>]+class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
        html_content,
        re.DOTALL
    )
    for msg_id, raw_text in pattern:
        # Clean HTML tags
        clean = re.sub(r'<[^>]+>', ' ', raw_text)
        clean = html.unescape(clean).strip()
        if clean:
            messages.append({"id": msg_id, "text": clean})
    return messages

def parse_signals(text: str, msg_id: str) -> list:
    """Extracts structured signals from message text."""
    if not text:
        return []
    text_lower = text.lower()
    results = []
    for alias, symbol in SYMBOL_MAP.items():
        if alias in text_lower:
            bull_score = sum(1 for w in BULL_WORDS if w in text_lower)
            bear_score = sum(1 for w in BEAR_WORDS if w in text_lower)
            if bull_score == 0 and bear_score == 0:
                continue
            direction = 1 if bull_score >= bear_score else -1
            total = bull_score + bear_score
            strength = round(max(bull_score, bear_score) / total, 2) if total > 0 else 0.5
            results.append({
                "msg_id": msg_id,
                "symbol": symbol,
                "direction": direction,
                "strength": strength,
                "raw": text[:200],
                "timestamp": time.time(),
                "used": False,
            })
    return results

def save_signals_to_json():
    """Saves the latest signals to a JSON file for the Dashboard."""
    try:
        with _signals_lock:
            # Create a copy to work safely with data
            current_signals = list(channel_signals)

        formatted_signals = []
        # Take the 10 latest signals and reverse (newest on top)
        for s in reversed(current_signals[-10:]):
            action = "LONG 🟢" if s["direction"] == 1 else "SHORT 🔴"
            # Convert Unix timestamp to readable time
            time_str = datetime.datetime.fromtimestamp(s["timestamp"]).strftime('%H:%M:%S')

            formatted_signals.append({
                "symbol": s["symbol"],
                "action": action,
                "time": time_str,
                "strength": s["strength"]
            })

        with open(TG_JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump({"signals": formatted_signals}, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"[TG READER] JSON save error: {e}")

def add_signals(signals: list):
    with _signals_lock:
        channel_signals.extend(signals)
        if len(channel_signals) > 100:
            del channel_signals[:len(channel_signals) - 100]

    # Trigger save immediately after adding new signals
    save_signals_to_json()

def get_recent_signal(symbol: str, max_age_seconds: int = 3600):
    """Returns the latest unused signal for a given symbol."""
    now = time.time()
    with _signals_lock:
        candidates = [
            s for s in channel_signals
            if s["symbol"] == symbol
            and not s["used"]
            and (now - s["timestamp"]) < max_age_seconds
        ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x["timestamp"], reverse=True)[0]

def mark_signal_used(symbol: str):
    with _signals_lock:
        for s in reversed(channel_signals):
            if s["symbol"] == symbol and not s["used"]:
                s["used"] = True
                break

def poll_channel():
    """Main scraping loop – runs in a separate thread."""
    global _last_seen_ids
    print(f"[TG READER] Starting scraper: {CHANNEL_URL}", flush=True)
    
    # First fetch
    html_content = fetch_channel_html()
    if html_content:
        messages = parse_html_messages(html_content)
        for m in messages:
            if m["id"] not in _last_seen_ids:
                _last_seen_ids.add(m["id"])
                sigs = parse_signals(m["text"], m["id"])
                if sigs:
                    add_signals(sigs)
        print(f"[TG READER] History loaded. Messages: {len(messages)} | Signals: {len(channel_signals)}", flush=True)
    
    while True:
        time.sleep(POLL_INTERVAL)
        try:
            html_content = fetch_channel_html()
            if not html_content:
                continue
            messages = parse_html_messages(html_content)
            new_count = 0
            for m in messages:
                if m["id"] not in _last_seen_ids:
                    _last_seen_ids.add(m["id"])
                    sigs = parse_signals(m["text"], m["id"])
                    if sigs:
                        add_signals(sigs)
                        new_count += len(sigs)
                        for s in sigs:
                            dir_text = "LONG" if s["direction"] == 1 else "SHORT"
                            print(f"[TG READER] New signal: {s['symbol']} {dir_text} ({s['strength']:.0%})", flush=True)
            if new_count:
                print(f"[TG READER] Added {new_count} new signals.", flush=True)
        except Exception as e:
            print(f"[TG READER] Polling error: {e}", flush=True)

def start_reader_thread():
    """Starts the scraper in the background (daemon thread)."""
    t = threading.Thread(target=poll_channel, daemon=True)
    t.start()
    print("[TG READER] Scraper thread started.", flush=True)

if __name__ == "__main__":
    # Local test
    print(f"=== Testing scraper for {CHANNEL_ID} ===")
    html_c = fetch_channel_html()
    if html_c:
        msgs = parse_html_messages(html_c)
        print(f"Found {len(msgs)} messages.")
        for m in msgs[-5:]:
            print(f"  [{m['id']}] {m['text'][:100]}")
        print("\nParsing signals...")
        for m in msgs:
            sigs = parse_signals(m["text"], m["id"])
            for s in sigs:
                dir_text = "LONG" if s["direction"] == 1 else "SHORT"
                print(f"  SIGNAL: {s['symbol']} {dir_text} (strength: {s['strength']:.0%}) – {s['raw'][:80]}")
    else:
        print("Failed to fetch channel page.")
