from dotenv import load_dotenv
# Load variables from .env file (required for manual execution)
load_dotenv(override=True)

import urllib.request as request
import json
import ssl
import time
import hmac
import hashlib
import subprocess
import sys
import os
import threading
import websocket
import ai_gateway
import gmail_intel_bridge
import version

# BotMemory — Persistent Memory Layer (SQLite + Redis)
try:
    import memory as bot_memory
    BOT_MEMORY_OK = True
except Exception as _mem_err:
    BOT_MEMORY_OK = False
    print(f"[MEMORY] Unavailable: {_mem_err}")

try:
    import ai_lesson_extractor
    LESSON_EXTRACTOR_OK = True
except Exception as _le_err:
    LESSON_EXTRACTOR_OK = False
    print(f"[LESSON EXTRACTOR] Loading error: {_le_err}", flush=True)

try:
    import circuit_breaker
    CIRCUIT_BREAKER_OK = True
except Exception as _cb_err:
    CIRCUIT_BREAKER_OK = False
    print(f"[CIRCUIT BREAKER] Loading error: {_cb_err}", flush=True)

# Telegram Channel Signal Intelligence
try:
    import telegram_reader
    TG_READER_AVAILABLE = True
except ImportError:
    TG_READER_AVAILABLE = False
    print("[V12.0] telegram_reader.py unavailable. Channel signals disabled.", flush=True)

# Data Nexus Worker Integration
try:
    import ai_nexus_worker
    NEXUS_WORKER_AVAILABLE = True
except ImportError:
    NEXUS_WORKER_AVAILABLE = False
    print("[V19.0] ai_nexus_worker.py unavailable. Automatic Nexus updates disabled.", flush=True)

# AI Dictator initializing via ai_gateway (REST Bridge)
if not os.environ.get("GEMINI_API_KEY"):
    print("CRITICAL ERROR: GEMINI_API_KEY environment variable missing. Exiting.")
    sys.exit(1)

# BYBIT GATEWAY INTEGRATION (v23.0 - NATIVE)
from bybit_gateway import BybitGateway
bybit = BybitGateway() # Mode depends on CCXT configuration in gateway

# Telegram Configuration
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

ctx = ssl.create_default_context()

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT"] # [v22.0.0] Altcoin Spring
LEARNING_FILE = 'autonomic_learning.json'
INTERVAL = '15m' # or 1h, 4h
MACRO_INTERVAL = '4h' # Added to verify broader trend
RISK_PERCENT = 0.01  # Restored to 0.01 (too frequent stop-losses with aggressive SL)

NEXUS_STATE_FILE = 'nexus_state.json'
FEAR_GREED_API = 'https://api.alternative.me/fng/?limit=1'
SERVER_TIME_OFFSET = 0 # Time sync offset (ms)

# --- GLOBAL TRACKING STATE (v16.2 Refactored) ---
# Symbol-level locks to prevent concurrent AI evaluations
SYMBOL_LOCKS = {s: threading.Lock() for s in SYMBOLS}

# [v24.2] Global execution gate — serializes order placement across threads.
# Prevents race condition where all threads see "enough balance" simultaneously.
# No hard position limit — each order is gated by real-time margin check inside the lock.
ORDER_EXECUTION_LOCK = threading.Lock()

GLOBAL_STATE = {
    "klines_cache": {sym: [] for sym in SYMBOLS},
    "last_ai_call": {sym: time.time() for sym in SYMBOLS},
    "last_close_time": {sym: 0 for sym in SYMBOLS}, # V21.9.0 Anti-Churn Lockdown
    "last_ai_price": {sym: 0 for sym in SYMBOLS},
    "is_evaluating_ai": {sym: False for sym in SYMBOLS},
    "last_reflection_time": 0, # V21.9.2: Global reflection cooldown
    "last_evaluation": {sym: time.time() for sym in SYMBOLS},
    "last_rsi": {sym: 50 for sym in SYMBOLS},
    "last_ema_side": {sym: None for sym in SYMBOLS}, # 'above' or 'below'
    "msg_counter": {sym: 0 for sym in SYMBOLS},
    "last_optimization": 0,
    "listen_key": None,
    "last_report_hour": -1,
    "last_report_day": -1,
    "last_nexus_hour": -1,
    "open_trades": {
        sym: {"entry_price": 0, "best_price": 0, "current_sl": 0, "algo_id": None, "side": None, "qty": 0, "qty_at_start": 0, "active": False, "tp_1": 0, "tp_2": 0, "tp_3": None, "tp_4": None, "tp_level": 0, "tp1_hit": False, "tp2_hit": False, "tp_order_ids": [], "is_expanding": False, "last_pos_check": 0}
        for sym in SYMBOLS
    },
    "exchange_info": None
}

learn_data = {"parameters": {}} # Always start with the correct structure

# --- OPT v22.3.0: mtime-based disk I/O cache for learning data ---
_learn_data_cache = None
_learn_data_mtime = 0.0

def load_learning_data():
    global _learn_data_cache, _learn_data_mtime
    try:
        if os.path.exists(LEARNING_FILE):
            mtime = os.path.getmtime(LEARNING_FILE)
            if _learn_data_cache is not None and mtime == _learn_data_mtime:
                return _learn_data_cache  # Cache hit — no disk read
            with open(LEARNING_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                if "parameters" not in data:
                    data["parameters"] = {}
                _learn_data_cache = data
                _learn_data_mtime = mtime
                return _learn_data_cache
    except Exception as e:
        print(f"[ERROR] Cannot read {LEARNING_FILE}: {e}")
    if _learn_data_cache is not None:
        return _learn_data_cache  # Return previous version on error
    return {"parameters": {}}

# --- CRITICAL ADDITION: LOADING DATA INTO GLOBAL VARIABLE ---
learn_data = load_learning_data()
GLOBAL_STATE['last_report_day'] = learn_data.get('last_report_day', -1)
print(f"[LEARN] Initialized parameters for: {list(learn_data.get('parameters', {}).keys())}")

def save_learning_data(data):
    global _learn_data_cache, _learn_data_mtime
    with open(LEARNING_FILE, 'w') as f:
        json.dump(data, f, indent=4)
    # Update cache immediately after saving (avoids redundant read)
    _learn_data_cache = data
    try:
        _learn_data_mtime = os.path.getmtime(LEARNING_FILE)
    except Exception:
        _learn_data_mtime = time.time()

def load_nexus_state():
    if os.path.exists(NEXUS_STATE_FILE):
        try:
            with open(NEXUS_STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Nexus State file analysis error: {e}", flush=True)
    # Default safe state if file is missing
    return {"nexus_score": 5.0, "macro_bias": "NEUTRAL"}

# --- OPT v22.3.0: TTL cache for FGI (changes at most once per day) ---
_fgi_cache = {"value": 50, "ts": 0.0}

def get_fear_greed_index():
    if time.time() - _fgi_cache["ts"] < 3600:  # 60-minute TTL
        return _fgi_cache["value"]
    try:
        req = request.Request(FEAR_GREED_API, method='GET', headers={'User-Agent': 'Mozilla/5.0'})
        with request.urlopen(req, timeout=10, context=ctx) as response:
            raw_data = response.read().decode()
            if not raw_data: return _fgi_cache["value"]
            data = json.loads(raw_data)
            if 'data' in data and len(data['data']) > 0:
                value = int(data['data'][0]['value'])
                _fgi_cache["value"] = value
                _fgi_cache["ts"] = time.time()
                return value
    except Exception as e:
        print(f"[WARN] Fear & Greed API error: {e}", flush=True)
    return _fgi_cache["value"]  # Return last known on error

def get_recent_exchange_trades(limit=5):
    """V23.0: Fetches raw trade history from Bybit PnL Gateway."""
    try:
        all_trades = []
        for sym in SYMBOLS:
            trades = bybit.get_closed_pnl(symbol=sym, limit=limit)
            if trades:
                all_trades.extend(trades)
        
        if not all_trades:
            return "No data from exchange."
        
        formatted_trades = []
        for t in all_trades:
            side = t.get('side', 'N/A')
            # Check for multiple possible keys for pnl depending on ccxt version/method fallback
            pnl_val = t.get('closedPnl', t.get('realizedPnl', t.get('info', {}).get('closedPnl', 0)))
            try:
                pnl = float(pnl_val)
            except:
                pnl = 0.0
            symbol = t.get('symbol', 'N/A')
            ts = t.get('updatedTime', t.get('timestamp', 0))
            if ts:
                t_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(ts)/1000))
            else:
                t_time = "N/A"
            formatted_trades.append(f"[{t_time}] {symbol} {side} PnL: {pnl:.2f} USDT")
            
        return "\n".join(formatted_trades)
    except Exception as e:
        print(f"Trade history fetch error: {e}")
        return "Exchange read error."

def send_telegram_message(text, force=False):
    if not force:
        return
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    def _send(txt, mode="Markdown"):
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload_dict = {"chat_id": TELEGRAM_CHAT_ID, "text": txt}
        if mode: payload_dict["parse_mode"] = mode
        payload = json.dumps(payload_dict).encode()
        headers = {"Content-Type": "application/json"}
        req = request.Request(url, data=payload, headers=headers, method='POST')
        with request.urlopen(req, timeout=10, context=ctx) as response:
            return True
        return False

    # Telegram has a 4096 character limit per message
    MAX_LENGTH = 4000
    chunks = [text[i:i + MAX_LENGTH] for i in range(0, len(text), MAX_LENGTH)]

    for chunk in chunks:
        try:
            _send(chunk, "Markdown")
        except Exception as e:
            try:
                # Fallback to plain text in case of AI formatting errors or length issues
                _send(chunk, mode=None)
            except Exception as e2:
                print(f"Telegram notification send error: HTTP E1: {e} | HTTP E2: {e2}", flush=True)

def sync_server_time():
    """V23.0: Bybit V5 uses GMT, system time synchronization."""
    try:
        server_time = bybit.exchange.milliseconds()
        local_time = int(time.time() * 1000)
        print(f"[{version.VERSION}] Bybit time sync: Local={local_time}, Server={server_time}", flush=True)
    except Exception as e:
        print(f"[{version.VERSION}] Time error: {e}", flush=True)

def binance_request(endpoint, query_string="", method='GET', silent=False):
    # --- MOCKED BINANCE ADAPTER FOR BYBIT DASHBOARD COMPATIBILITY ---
    try:
        from urllib.parse import parse_qs
    except ImportError: pass

    try:
        if endpoint == '/fapi/v2/balance':
            bal = bybit.get_balance()
            return [{
                "asset": "USDT",
                "balance": str(bal.get('wallet', 0)),
                "availableBalance": str(bal.get('available', 0)),
                "crossUnPnl": str(bal.get('unrealized_pnl', 0))
            }]
        
        elif endpoint == '/fapi/v2/positionRisk':
            pos_list = bybit.exchange.fetch_positions()
            res = []
            for p in pos_list:
                if float(p.get('contracts', 0)) > 0:
                    side_mult = 1 if p.get('side') == 'long' else -1
                    created_time_ms = float(p.get('info', {}).get('createdTime', p.get('timestamp') or (time.time() * 1000)))
                    res.append({
                        "symbol": p.get('symbol'),
                        "positionAmt": str(float(p.get('contracts', 0)) * side_mult),
                        "entryPrice": str(p.get('entryPrice', 0)),
                        "markPrice": str(p.get('markPrice', 0)),
                        "unRealizedProfit": str(p.get('unrealizedPnl', 0)),
                        "leverage": str(p.get('leverage', 1)),
                        "liquidationPrice": str(p.get('liquidationPrice', 0)),
                        "updateTime": int(created_time_ms)
                    })
            return res
            
        elif endpoint in ['/fapi/v1/openOrders', '/fapi/v1/openAlgoOrders']:
            qs = parse_qs(query_string)
            symbol = qs.get('symbol', [''])[0]
            if not symbol: return []
            base = symbol.replace("/", "").replace(":USDT", "").replace("USDT", "")
            orders = bybit.exchange.fetch_open_orders(f"{base}/USDT:USDT")
            res = []
            for o in orders:
                info = o.get('info', {})
                order_type = 'LIMIT'
                if info.get('orderType') == 'Stop' or info.get('stopOrderType') in ['TakeProfit', 'StopLoss']:
                    order_type = 'STOP_MARKET' if info.get('stopOrderType') == 'StopLoss' else 'TAKE_PROFIT'
                
                # Bybit reduces true/false might be string or boolean
                reduce_only = str(info.get('reduceOnly', '')).lower() == 'true' or info.get('reduceOnly') is True
                
                res.append({
                    "symbol": symbol,
                    "reduceOnly": reduce_only,
                    "type": order_type,
                    "orderType": order_type,
                    "price": str(o.get('price', 0) or o.get('stopPrice', 0) or 0),
                    "stopPrice": str(info.get('triggerPrice', 0) or o.get('stopPrice', 0) or 0),
                    "triggerPrice": str(info.get('triggerPrice', 0) or o.get('stopPrice', 0) or 0),
                    "orderId": str(o.get('id', '')),
                    "algoId": str(o.get('id', ''))
                })
            return res
            
        elif endpoint in ['/fapi/v1/algoOrder', '/fapi/v1/order'] and method == 'DELETE':
            qs = parse_qs(query_string)
            symbol = qs.get('symbol', [''])[0]
            order_id = qs.get('algoId', qs.get('orderId', ['']))[0]
            if symbol and order_id:
                base = symbol.replace("/", "").replace(":USDT", "").replace("USDT", "")
                try: bybit.exchange.cancel_order(order_id, f"{base}/USDT:USDT")
                except: pass
            return {}
            
        elif endpoint == '/fapi/v1/userTrades':
            return [] # Mocked for cleanup routines
    except Exception as e:
        print(f"[Bybit Mock] Adapter Error for {endpoint}: {e}")
        
    return []

def get_klines(symbol, interval, limit=500):
    try:
        # ccxt intervals: '1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d'
        base = symbol.replace("/", "").replace(":USDT", "").replace("USDT", "")
        symbol_ccxt = f"{base}/USDT:USDT"
        ohlcv = bybit.exchange.fetch_ohlcv(symbol_ccxt, timeframe=interval, limit=limit)
        # return map: [{open, high, low, close}] matching Binance format expected
        return [{"open": float(x[1]), "high": float(x[2]), "low": float(x[3]), "close": float(x[4])} for x in ohlcv]
    except Exception as e:
        print(f"Klines fetch error for {symbol}: {e}")
        return []

def get_balance():
    """
    V21.14.2: Returns both Wallet Balance (Total) and Available Balance (Margin).
    """
    res = binance_request('/fapi/v2/balance')
    result = {'wallet': 0.0, 'available': 0.0}
    if res and isinstance(res, list):
        for b in res:
            if b.get('asset') == 'USDT':
                result['wallet'] = float(b.get('balance', 0))
                result['available'] = float(b.get('availableBalance', 0))
                return result
    return result

# Bybit native private WSS is handled within BybitGateway.
def get_listen_key():
    return "BYBIT_NATIVE_STREAM"

def keepalive_listen_key():
    pass

def set_leverage(symbol, leverage):
    """v23.0: Sets Bybit V5 leverage."""
    try:
        print(f"[{symbol}] Setting Bybit leverage: x{leverage}...", flush=True)
        bybit.set_leverage(symbol, leverage)
        return True
    except Exception as e:
        print(f"[{symbol}] Leverage set error: {e}")
        return False

def calculate_ema(prices, period):
    if not prices or len(prices) < period:
        return 0.0
    k = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return ema

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    
    gains = []
    losses = []
    
    for i in range(1, period + 1):
        change = prices[i] - prices[i-1]
        gains.append(max(0, change))
        losses.append(max(0, -change))
        
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    
    for i in range(period + 1, len(prices)):
        change = prices[i] - prices[i-1]
        gain = max(0, change)
        loss = max(0, -change)
        
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calculate_rsi_array(prices, period=14):
    if len(prices) < period + 1:
        return [50.0] * len(prices)
    
    rsi_list = [50.0] * period
    gains = []
    losses = []
    
    for i in range(1, period + 1):
        change = prices[i] - prices[i-1]
        gains.append(max(0, change))
        losses.append(max(0, -change))
        
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    
    if avg_loss == 0:
        rsi_list.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_list.append(100.0 - (100.0 / (1.0 + rs)))
        
    for i in range(period + 1, len(prices)):
        change = prices[i] - prices[i-1]
        gain = max(0, change)
        loss = max(0, -change)
        
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        
        if avg_loss == 0:
            rsi_list.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_list.append(100.0 - (100.0 / (1.0 + rs)))
            
    return rsi_list

def calculate_macd(prices, fast_period=12, slow_period=26, signal_period=9):
    if len(prices) < slow_period + signal_period:
        return {'macd': 0, 'signal': 0, 'hist': 0, 'hist_slope': 'FLAT'}
        
    def _ema(data, period):
        emas = [sum(data[:period]) / period]
        multiplier = 2 / (period + 1)
        for p in data[period:]:
            emas.append((p - emas[-1]) * multiplier + emas[-1])
        return emas

    fast_emas = _ema(prices, fast_period)
    slow_emas = _ema(prices, slow_period)
    
    start_idx = slow_period - fast_period
    fast_emas = fast_emas[start_idx:]
    
    macd_line = [f - s for f, s in zip(fast_emas, slow_emas)]
    signal_line = _ema(macd_line, signal_period)
    
    macd_line = macd_line[signal_period - 1:]
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    
    if len(hist) >= 2:
        slope = "RISING (Bullish Momentum)" if hist[-1] > hist[-2] else "FALLING (Bearish Momentum)"
    else:
        slope = "FLAT"
        
    return {
        'macd': macd_line[-1],
        'signal': signal_line[-1],
        'hist': hist[-1],
        'hist_slope': slope
    }

def detect_divergences(klines, period=14):
    if len(klines) < period * 2:
        return "NONE"
        
    closes = [float(k['close']) for k in klines]
    highs = [float(k['high']) for k in klines]
    lows = [float(k['low']) for k in klines]
    rsis = calculate_rsi_array(closes, period)
    
    peaks = []
    troughs = []
    
    for i in range(period, len(closes)-2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            peaks.append(i)
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            troughs.append(i)
            
    div_signal = "NONE"
    
    if len(peaks) >= 2:
        p1, p2 = peaks[-2], peaks[-1]
        if (len(closes) - p2) <= 15:
            if highs[p2] > highs[p1] and rsis[p2] < rsis[p1] - 2:
                div_signal = "🔴 BEARISH DIVERGENCE (Price High, RSI Low)"
                
    if len(troughs) >= 2:
        t1, t2 = troughs[-2], troughs[-1]
        if (len(closes) - t2) <= 15:
            if lows[t2] < lows[t1] and rsis[t2] > rsis[t1] + 2:
                div_signal = "🟢 BULLISH DIVERGENCE (Price Low, RSI High)"
                
    return div_signal

def analyze_price_action_structure(klines, depth=3):
    swings = get_swing_points(klines, depth=depth)
    if len(swings) < 4:
        return "Insufficient structure data"
        
    peaks = [s['price'] for s in swings if s['type'] == 'PEAK']
    troughs = [s['price'] for s in swings if s['type'] == 'TROUGH']
    
    desc = []
    if len(peaks) >= 2:
        if peaks[-1] > peaks[-2]:
            desc.append("Higher Highs (HH)")
        else:
            desc.append("Lower Highs (LH)")
            
    if len(troughs) >= 2:
        if troughs[-1] > troughs[-2]:
            desc.append("Higher Lows (HL)")
        else:
            desc.append("Lower Lows (LL)")
            
    if "Higher Highs (HH)" in desc and "Higher Lows (HL)" in desc:
        return "BULLISH STRUCTURE (HH, HL) - Uptrend confirmed."
    elif "Lower Highs (LH)" in desc and "Lower Lows (LL)" in desc:
        return "BEARISH STRUCTURE (LH, LL) - Downtrend confirmed."
    elif "Lower Highs (LH)" in desc and "Higher Lows (HL)" in desc:
        return "CONSOLIDATION (LH, HL) - Symmetrical Triangle / Squeeze."
    elif "Higher Highs (HH)" in desc and "Lower Lows (LL)" in desc:
        return "EXPANDING VOLATILITY (HH, LL) - Megaphone pattern, unsafe."
    
    return "MIXED STRUCTURE - No clear trend."

def calculate_atr(klines, period=14):
    if len(klines) < period + 1:
        return 0.0
    
    true_ranges = []
    for i in range(1, len(klines)):
        high = klines[i]['high']
        low = klines[i]['low']
        prev_close = klines[i-1]['close']
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
        
    atr = sum(true_ranges[:period]) / period
    for i in range(period, len(true_ranges)):
        atr = (atr * (period - 1) + true_ranges[i]) / period
        
    return atr

def get_order_book_imbalance(symbol, current_price, limit=50, threshold_pct=0.01):
    """v23.0: Uses Bybit V5 for order book imbalance analysis."""
    try:
        # Bybit V5 Orderbook
        res = bybit.exchange.fetch_order_book(symbol, limit=limit)
        bids = res.get('bids', [])
        asks = res.get('asks', [])
        
        lower_bound = current_price * (1 - threshold_pct)
        upper_bound = current_price * (1 + threshold_pct)
        
        bid_vol = sum([p * q for p, q in bids if p >= lower_bound])
        ask_vol = sum([p * q for p, q in asks if p <= upper_bound])
        
        total_vol = bid_vol + ask_vol
        if total_vol == 0: return "Low liquidity in range."
        
        bid_pct = (bid_vol / total_vol) * 100
        ask_pct = (ask_vol / total_vol) * 100
        domination = "BIDS" if bid_pct > ask_pct else "ASKS"
        
        return f"Imbalance: {domination} ({bid_pct:.1f}% vs {ask_pct:.1f}%)."
    except Exception as e:
        return f"OrderBook Unavailable ({e})"

def report_closed_position(symbol, side):
    """v23.0: Fetches PnL from Bybit after closing a position."""
    try:
        time.sleep(3.0) # Wait for Bybit settlement
        trades = bybit.get_closed_pnl(symbol=symbol, limit=5)
        if not trades:
            send_telegram_message(f"🏁 *[{symbol}] POSITION CLOSED*\nStatus: `FILLED` (PnL on its way...)")
            return

        # Fetching the latest PnL trade
        last_trade = trades[0]
        pnl = float(last_trade.get('closedPnl', 0))
        fee = 0 # CCXT v5 nie zawsze zwraca fee w tym endpointcie
        
        emoji = "🟢 PROFIT" if pnl > 0 else "🔴 LOSS"
        msg = f"🏁 *[{symbol}] POSITION CLOSED on Bybit*\n\n{emoji}: `{pnl:+.2f} USDT`"
        send_telegram_message(msg)
        
        # Logging and AI learning
        time_str = time.strftime('%Y-%m-%d %H:%M:%S')
        with open('engine_trades.log', 'a') as f:
            f.write(f"[{time_str}] CLOSED {symbol} | PnL: {pnl:+.2f} USDT | Side: {side}\n")

        # Performance metrics
        try:
            learn_data = load_learning_data()
            metrics = learn_data.setdefault("performance_metrics", {"total_trades": 0, "winning_trades": 0, "total_pnl": 0.0, "per_symbol": {}})
            metrics["total_trades"] += 1
            if pnl > 0: metrics["winning_trades"] += 1
            metrics["total_pnl"] = round(metrics["total_pnl"] + pnl, 4)
            save_learning_data(learn_data)
        except: pass

        GLOBAL_STATE['last_close_time'][symbol] = time.time()
        
        # Reflection Trigger on loss
        if pnl < 0:
            now = time.time()
            if now - GLOBAL_STATE.get('last_reflection_time', 0) > 1800:
                subprocess.Popen([sys.executable, "reflection_session.py"], start_new_session=True)
                GLOBAL_STATE['last_reflection_time'] = now
    except Exception as e:
        print(f"[{symbol}] report_closed_position error: {e}")

def calculate_adx(klines, period=14):
    if len(klines) < period * 2:
        return 50.0
        
    trs = []
    pos_dms = []
    neg_dms = []
    
    for i in range(1, len(klines)):
        high = klines[i]['high']
        low = klines[i]['low']
        prev_high = klines[i-1]['high']
        prev_low = klines[i-1]['low']
        prev_close = klines[i-1]['close']
        
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        
        up_move = high - prev_high
        down_move = prev_low - low
        
        if up_move > down_move and up_move > 0:
            pos_dms.append(up_move)
        else:
            pos_dms.append(0)
            
        if down_move > up_move and down_move > 0:
            neg_dms.append(down_move)
        else:
            neg_dms.append(0)
            
    smooth_tr = sum(trs[:period])
    smooth_pos_dm = sum(pos_dms[:period])
    smooth_neg_dm = sum(neg_dms[:period])
    
    dx_vals = []
    for i in range(period, len(trs)):
        smooth_tr = smooth_tr - (smooth_tr / period) + trs[i]
        smooth_pos_dm = smooth_pos_dm - (smooth_pos_dm / period) + pos_dms[i]
        smooth_neg_dm = smooth_neg_dm - (smooth_neg_dm / period) + neg_dms[i]
        
        if smooth_tr == 0:
            dx = 0
        else:
            pos_di = 100 * (smooth_pos_dm / smooth_tr)
            neg_di = 100 * (smooth_neg_dm / smooth_tr)
            if pos_di + neg_di == 0:
                dx = 0
            else:
                dx = 100 * abs(pos_di - neg_di) / (pos_di + neg_di)
        dx_vals.append(dx)
        
    if not dx_vals:
        return 50.0
        
    adx = sum(dx_vals[:period]) / period if len(dx_vals) >= period else sum(dx_vals) / len(dx_vals)
    for i in range(period, len(dx_vals)):
        adx = ((adx * (period - 1)) + dx_vals[i]) / period
        
    return adx

def detect_sfp(klines, lookback=20):
    """
    V21.0: Detects Swing Failure Pattern (SFP).
    Identifies if the last candle swept a recent high/low but closed back inside.
    """
    if len(klines) < lookback + 2: return None
    
    last = klines[-1]
    prev_klines = klines[-(lookback+1):-1]
    
    highest_high = max([k['high'] for k in prev_klines])
    lowest_low = min([k['low'] for k in prev_klines])
    
    # Bearish SFP (Sweep of High)
    if last['high'] > highest_high and last['close'] < highest_high:
        return "BEARISH_SFP"
    
    # Bullish SFP (Sweep of Low)
    if last['low'] < lowest_low and last['close'] > lowest_low:
        return "BULLISH_SFP"
        
    return None

def get_market_symmetry():
    """
    V21.0: Checks if BTC and ETH are in sync relative to their 50-period EMA.
    Returns 1 for Bullish Sync, -1 for Bearish Sync, 0 for Divergence.
    """
    btc_klines = GLOBAL_STATE['klines_cache'].get('BTCUSDT', [])
    eth_klines = GLOBAL_STATE['klines_cache'].get('ETHUSDT', [])
    
    if not btc_klines or not eth_klines: return 0
    
    btc_price = btc_klines[-1]['close']
    eth_price = eth_klines[-1]['close']
    
    btc_ema = calculate_ema([k['close'] for k in btc_klines], 50)
    eth_ema = calculate_ema([k['close'] for k in eth_klines], 50)
    
    btc_bullish = btc_price > btc_ema
    eth_bullish = eth_price > eth_ema
    
    if btc_bullish and eth_bullish: return 1
    if not btc_bullish and not eth_bullish: return -1
    return 0

def check_open_positions(symbol):
    """v23.0: Checks positions on Bybit."""
    try:
        pos = bybit.get_positions()
        for p in pos:
            sym = p.get('symbol_raw', p['symbol'])
            if sym == symbol and float(p.get('contracts', p.get('qty', 0))) != 0:
                return True
    except: pass
    return False

def check_open_orders(symbol):
    """v23.0: Checks pending orders on Bybit."""
    try:
        orders = bybit.exchange.fetch_open_orders(symbol)
        return len(orders) > 0
    except: return False

def cancel_all_orders(symbol):
    """v23.0: Cancels everything on Bybit."""
    try:
        bybit.exchange.cancel_all_orders(symbol)
        return True
    except: return False


def place_market_order(symbol, side, quantity, sl=0, tp=0, reduce_only=False):
    """v23.0: Market execution via Bybit Gateway."""
    try:
        # Passing SL/TP if available
        return bybit.place_market_order(symbol, side, quantity, sl_price=sl, tp_price=tp, reduce_only=reduce_only)
    except Exception as e:
        print(f"[{symbol}] Market Order error: {e}")
        return {"error": str(e)}

def load_exchange_info():
    """v23.0: Loads markets from CCXT/Bybit V5."""
    try:
        bybit.exchange.load_markets()
        print("[v23.0] Bybit Markets loaded successfully.")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to load Bybit markets: {e}")
        return False

def get_symbol_precision(symbol):
    """v23.0: Fetches QTY precision from CCXT."""
    try:
        import math
        # Converting symbol to CCXT format if needed
        ccxt_symbol = symbol
        if "/" not in symbol and ":" not in symbol:
             # Attempting to map ETHUSDT -> ETH/USDT:USDT
             for m_id, m_data in bybit.exchange.markets.items():
                 if m_data['id'] == symbol:
                     ccxt_symbol = m_id
                     break
        
        market = bybit.exchange.market(ccxt_symbol)
        prec = market['precision']['amount']
        print(f"DEBUG PREC: {symbol} -> {ccxt_symbol} | prec_raw={prec}", flush=True)
        if prec < 1:
            return int(-math.log10(prec))
        return int(prec)
    except Exception as e: 
        print(f"DEBUG PREC ERROR: {e}")
        return 3

def get_price_precision(symbol):
    """v23.0: Fetches price precision from CCXT."""
    try:
        import math
        market = bybit.exchange.market(symbol)
        prec = market['precision']['price']
        if prec < 1:
            return int(-math.log10(prec))
        return int(prec)
    except: return 2

def fire_bridge(symbol, order_id, side, sl, tp, qty):
    """v23.0: Bybit Native Bridge - TP/SL ustawiane przez Conditional Orders."""
    global GLOBAL_STATE
    price_precision = get_price_precision(symbol)
    
    approx_entry = GLOBAL_STATE['klines_cache'][symbol][-1]['close'] if GLOBAL_STATE['klines_cache'][symbol] else 0
    nowy_sl = round(sl, price_precision)
    tp_price = round(tp, price_precision)
    
    print(f"[{symbol}] Sending TP/SL to Bybit V5...", flush=True)
    
    # Bybit pozwala na mark_price jako trigger (podobnie jak binance workingType=MARK_PRICE)
    sl_res = bybit.create_order(symbol, 'stop_market', 'sell' if side == 'BUY' else 'buy', qty, 
                               params={'stopPrice': nowy_sl, 'triggerBy': 'MarkPrice', 'reduceOnly': True})
    
    tp_res = bybit.create_order(symbol, 'limit', 'sell' if side == 'BUY' else 'buy', qty, tp_price, 
                               params={'reduceOnly': True})
    
    tp_order_ids = []
    if tp_res and 'id' in tp_res: tp_order_ids.append(tp_res['id'])
    
    algo_id = sl_res.get('id') if sl_res else None

    GLOBAL_STATE['open_trades'][symbol] = {
        "entry_price": approx_entry,
        "best_price": approx_entry,
        "current_sl": nowy_sl,
        "algo_id": algo_id,
        "stop_order_id": algo_id, # Bybit terminology
        "side": side,
        "qty": qty,
        "qty_at_start": qty,
        "active": True,
        "entry_time": time.time(),
        "tp_1": tp_price,
        "tp_2": tp_price, # Bybit V1 single TP for now, simpler
        "tp1_hit": False,
        "tp2_hit": False,
        "tp_order_ids": tp_order_ids,
        "last_pos_check": time.time()
    }
    
    emoji = "🟢" if side == "BUY" else "🔴"
    dir_text = "LONG" if side == "BUY" else "SHORT"
    send_telegram_message(f"{emoji} *[{symbol}] POSITION OPENED ({dir_text})*\n*Entry:* `{approx_entry}`\n*SL:* `{nowy_sl}`\n*TP:* `{tp_price}`\n*Qty:* `{qty}`")
    
    print(f"[{symbol}] Position successfully executed. Trailing started.")

def log_trade(action, symbol, quantity, price, sl, tp, leverage, reason):
    time_str = time.strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{time_str}] {action} {quantity} {symbol} @ {price} | LEVERAGE: x{leverage} | SL: {sl} | TP: {tp} | {reason}\n"
    with open('engine_trades.log', 'a') as f:
        f.write(log_line)
        
    master_backup_entry = f"- **{time_str}**: **[v17.0 AUTO EXECUTION]** {action} {symbol} | Qty: {quantity} | Prc: {price} | Leverage: x{leverage} | SL: {sl} | TP: {tp} | Reason: {reason}\n"
    try:
        with open('MASTER_BACKUP.md', 'r') as f:
            lines = f.readlines()
            
        for i, line in enumerate(lines):
            if line.startswith('### B. Historical Decision Log'):
                lines.insert(i + 1, master_backup_entry)
                break
                
        with open('MASTER_BACKUP.md', 'w') as f:
            f.writelines(lines)
    except Exception as e:
        print(f"MASTER_BACKUP.md update error: {e}")




def archive_to_black_box(title, report_content):
    """
    V21.2: Permanent Archival to BLACK_BOX.md.
    """
    time_str = time.strftime('%Y-%m-%d %H:%M:%S')
    entry = f"\n## [{time_str}] {title}\n\n{report_content}\n"
    entry += "\n---\n"
    try:
        with open('BLACK_BOX.md', 'a') as f:
            f.write(entry)
        print(f"[BLACK_BOX] Archived report: {title}")
    except Exception as e:
        print(f"BLACK_BOX.md write error: {e}")

def generate_master_daily_report(compression_summary=""):
    """
    V23.8: MASTER DAILY REPORT (High-Fidelity) + RL Compression
    Merges market analysis and self-learning into a single, professional document 
    modeled after IT Tech's "On-chain Insights".
    """
    balance_data = get_balance()
    wallet_bal = balance_data['wallet']
    avail_bal = balance_data['available']
    fgi = get_fear_greed_index()
    nexus = load_nexus_state()
    learn_data = load_learning_data()
    metrics = learn_data.get("performance_metrics", {})
    
    # 1. Collecting lessons (Knowledge Base)
    lessons = ""
    for k, v in learn_data.items():
        if k.startswith("ai_lessons_learned"):
            symbol = k.replace("ai_lessons_learned_", "")
            lessons += f"- **{symbol}**: {v}\n"

    # 2. Logi silnika (10 linii dla szerszego kontekstu)
    recent_logs = "No logs."
    try:
        if os.path.exists('engine_trades.log'):
            with open('engine_trades.log', 'r') as f:
                lines = f.readlines()
                recent_logs = "".join(lines[-10:])
    except: pass

    # 3. Telegram Signals (Alpha Signals Channel)
    tg_signals = "No active signals."
    if TG_READER_AVAILABLE:
        with telegram_reader._signals_lock:
            sigs = telegram_reader.channel_signals[-5:]
            if sigs:
                tg_signals = "\n".join([f"- {s['symbol']} {s['direction']} (strength: {s['strength']})" for s in sigs])

    # 4. Trend cluster overview (Live Data)
    market_overview = []
    for sym in SYMBOLS:
        if GLOBAL_STATE['klines_cache'][sym]:
            rsi = GLOBAL_STATE['last_rsi'].get(sym, 50)
            price = GLOBAL_STATE['klines_cache'][sym][-1]['close']
            market_overview.append(f"- {sym}: {price} (RSI: {rsi:.2f})")
    
    # 5. Exchange history (Ground Truth) - Optimization v22.4 (limit 50 -> 5)
    exchange_history = get_recent_exchange_trades(limit=5)

    # 6. Active Positions (Ground Truth)
    active_positions_list = bybit.get_positions()
    if active_positions_list:
        formatted_positions = []
        for p in active_positions_list:
            tps_str = ", ".join([str(tp) for tp in p['tps']]) if p.get('tps') else "None"
            formatted_positions.append(
                f"- {p['symbol_raw']}: {p['side']} @ {p['entry_price']} "
                f"(Size: {p['qty']}, SL: {p['sl']}, TP: {tps_str}, Unrealized PnL: {p['unrealized_pnl']:.2f} USDT)"
            )
        positions_str = "\n".join(formatted_positions)
    else:
        positions_str = "No active positions."

    prompt = f"""
Jesteś elitarnym systemem Antigravity AI {version.FULL_VERSION}, dostarczającym profesjonalne raporty "On-chain & Market Insights".
Twoim celem jest przygotowanie kompleksowego, strukturalnego raportu dla użytkownika, który łączy analizę makro, strukturę rynku i Twoją bieżącą ewolucję jako tradera na giełdzie Bybit.

IMPORTANT: Use ONLY single quotes (') inside the "telegram_message" and "new_lessons" text fields to avoid JSON syntax errors. NEVER use double quotes (") inside a JSON string.

--- INPUT DATA ---
Balance: {wallet_bal:.2f} USDT (Available: {avail_bal:.2f} USDT)
Fear & Greed Index: {fgi}
Nexus State: {nexus}
AI Performance Metrics: {metrics}
Active Positions (Ground Truth):
{positions_str}
AI Lessons Learned:
{lessons}
Recent Engine Trades:
{recent_logs}
Telegram Channel Signals:
{tg_signals}
Market Overview (Live):
{'\n'.join(market_overview)}
Recent Exchange Trades:
{exchange_history}
Compression Summary (Reinforcement Learning):
{compression_summary if compression_summary else 'No compression today.'}

--- TASK ---
Wygeneruj raport w formacie JSON, zawierający:
1. `telegram_message`: Profesjonalny, zwięzły raport w formacie Markdown, podsumowujący stan rynku, Twoje wnioski i kluczowe metryki. Skup się na:
    - Ogólnym sentymencie (FGI, Nexus).
    - **Podaj wyraźnie oba parametry salda** (Total Equity and Available Margin).
    - Bieżących otwartych pozycjach: W sekcji "Bieżące Otwarte Pozycje" (w "telegram_message") musisz wymienić DOKŁADNIE i WYŁĄCZNIE te pozycje, które są podane w "Active Positions (Ground Truth)" we wprowadzonych danych. Jeśli nie ma tam żadnej pozycji, napisz "Brak otwartych pozycji". Nie zmyślaj, nie zgaduj ani nie dodawaj pozycji, których tam nie ma.
    - Kluczowych ruchach cenowych i Twoich decyzjach.
    - Wnioskach z ostatnich transakcji (jeśli są).
    - Perspektywach na nadchodzący dzień.
    - Używaj emoji i formatowania Markdown dla czytelności.
2. `new_lessons`: JSON object where the key is the symbol (e.g. "BTCUSDT") and the value is a consolidated lesson extracted by the AI from the last 24h (e.g. "Market reacts to FGI > 70 with strong sell-offs, avoid LONGs in these conditions."). If no new lessons, return an empty object.

JSON structure example:
{{
    "telegram_message": "🚀 Antigravity AI {version.FULL_VERSION} ... \n\n💰 **BALANCE:** {wallet_bal:.2f} USDT (Available: {avail_bal:.2f} USDT)\n\n--- ...",
    "new_lessons": {{
        "BTCUSDT": "...",
        "ETHUSDT": "..."
    }}
}}
"""
    try:
        response_text = ai_gateway.generate_content(
            prompt=prompt,
            model="gemini-2.5-flash",
            response_mime="application/json",
            cache_key=f"daily_report_v5_{int(time.time())}",
            cooldown=21600,
            timeout=120
        )
        
        if not response_text:
            raise Exception("Gateway returned empty response")
            
        # Robust JSON cleaning for nested Markdown quotes
        try:
            ai_data = json.loads(response_text, strict=False)
        except json.JSONDecodeError:
            print("[REPORT] JSON error detected. Attempting automatic quote repair...", flush=True)
            # Simple heuristic: escape internal quotes that are not part of JSON structure
            # (Crude but often effective for LLM output)
            import re
            repaired = re.sub(r'(?<![:\[,])"(?![:,\]}])', "'", response_text)
            ai_data = json.loads(repaired, strict=False)
        report_msg = ai_data.get("telegram_message", "Failed to prepare Master report.")
        
        # Updating Knowledge Base (Knowledge Evolution)
        new_lessons = ai_data.get("new_lessons", {})
        if new_lessons:
            for symbol, consolidated_lesson in new_lessons.items():
                if consolidated_lesson and len(consolidated_lesson) > 5:
                    key = f"ai_lessons_learned_{symbol}"
                    learn_data[key] = consolidated_lesson
            save_learning_data(learn_data)
            print(f"[REPORT] AI knowledge base evolved as part of the Master report.")

        send_telegram_message(report_msg, force=True)
        print(f"[REPORT] Master Daily Report sent at {time.strftime('%H:%M:%S')}")
        
        # Archive to Black Box
        archive_to_black_box("MASTER DAILY REPORT", report_msg)

    except Exception as e:
        error_msg = f"⚠️ Master Report generation error: {e}"
        send_telegram_message(error_msg)
        print(error_msg)

def expand_tp_targets(symbol, current_price):
    """
    V21.5: Dynamic TP Expansion. 
    Asks the AI Dictator for a new target (TP3, TP4...) when previous milestones are hit.
    """
    global GLOBAL_STATE
    trade = GLOBAL_STATE['open_trades'][symbol]
    
    # print(f"[{symbol}] Rozpoczynam ekspansję TP (AI Request)...")
    learn_data = load_learning_data()
    nexus_state = load_nexus_state()
    fgi_score = get_fear_greed_index()
    
    current_tp_level = trade.get("tp_level", 0)
    achieved_tps = []
    if trade.get("tp1_hit"): achieved_tps.append(f"TP1: {trade['tp_1']}")
    if trade.get("tp2_hit"): achieved_tps.append(f"TP2: {trade['tp_2']}")
    if trade.get("tp_3"): achieved_tps.append(f"TP3: {trade['tp_3']}")
    
    prompt = f"""You are Antigravity AI {version.FULL_VERSION}. A trade is in progress and milestones were hit.
SYMBOL: {symbol}
SIDE: {trade['side']}
ENTRY: {trade['entry_price']}
CURRENT PRICE: {current_price}
ACHIEVED TARGETS: {', '.join(achieved_tps)}
MARKET BIAS: {nexus_state.get('macro_bias', 'NEUTRAL')} (Score: {nexus_state.get('nexus_score', 5.0)})

TASK: Calculate the NEXT logical Take Profit target (TP{current_tp_level + 2}) based on:
1. Elliott Wave extensions (e.g. if Wave 3 is running, look for 1.618/2.618 Fib of Wave 1).
2. Major order book levels or macro resistance/supports.
3. Volatility (ATR).

RESPONSE MUST BE JSON: {{"next_tp": float, "analysis": "string"}}
"""
    try:
        response_text = ai_gateway.generate_content(
            prompt=prompt,
            response_mime='application/json',
            cache_key=f"{symbol}_expansion",
            cooldown=900 # 15 mins (half of 30 mins)
        )
        
        if response_text:
            data = json.loads(response_text)
            next_tp = data.get("next_tp")
            if next_tp:
                price_precision = get_price_precision(symbol)
                next_tp = round(float(next_tp), price_precision)
                target_key = f"tp_{current_tp_level + 2}"
                trade[target_key] = next_tp
                send_telegram_message(f"🎯 *[{symbol}] TP EXPANSION ({target_key.upper()})*\nSuggested new target: `{next_tp}`\nAnalysis: {data.get('analysis', 'None')}")
                
                # REAL ORDER PLACEMENT ON BYBIT
                sl_side = 'sell' if trade['side'] == 'BUY' else 'buy'
                
                # Close old furthest TP
                existing_orders = trade.get("tp_order_ids", [])
                if existing_orders:
                    try:
                        bybit.exchange.cancel_order(existing_orders[-1], symbol)
                        trade["tp_order_ids"].pop()
                    except: pass
                
                # Place new target milestone
                res = bybit.create_order(symbol, 'limit', sl_side, trade['qty'] * 0.5, next_tp, params={'reduceOnly': True})
                if res and 'id' in res:
                    trade["tp_order_ids"].append(res['id'])
                    print(f"[{symbol}] Success: Bybit TP Expansion active (id: {res['id']})")
    except Exception as e:
        print(f"[{symbol}] Expansion AI error: {e}")
    finally:
        trade["is_expanding"] = False

def update_trailing_stop(symbol, current_price, params, atr):
    global GLOBAL_STATE
    trade = GLOBAL_STATE['open_trades'][symbol]
    if not trade["active"]:
        return
        
    old_sl = trade.get("current_sl", 0)
    force_update = trade.pop("force_sl_update", False) # Check if WebSocket or logic requested a forced update
        
    now = time.time()
    
    # ANTI-PHANTOM SAFETY CHECK (Every 60s)
    if now - trade.get("last_pos_check", 0) > 60:
        trade["last_pos_check"] = now
        pos_list = bybit.get_positions()
        pos = next((p for p in pos_list if p.get('symbol_raw', p['symbol']) == symbol), None)
        if not pos or float(pos.get('contracts', pos.get('qty', 0))) == 0:
            print(f"[{symbol}] POSITION CLOSED natively on Bybit (SL/TP hit). Cleaning up and fetching PnL...")
            trade["active"] = False
            cancel_all_orders(symbol)
            # V24.0: Since Bybit natively handles SL/Trailing Stop, we trigger the PnL report immediately.
            threading.Thread(target=report_closed_position, args=(symbol, trade['side']), daemon=True).start()
            return
        
    price_precision = get_price_precision(symbol)
    
    # 1. Checking and updating High/Low point 
    if trade["side"] == "BUY":
        if current_price > trade["best_price"]:
            trade["best_price"] = current_price
            
        ideal_sl = round(trade["best_price"] - (atr * params.get('atr_multiplier_sl', 1.5)), price_precision)
        
        # DYNAMIC LADDER LOGIC (BUY)
        # Check TP1
        if not trade["tp1_hit"] and trade["best_price"] >= trade["tp_1"] and trade["tp_1"] > 0:
            trade["tp1_hit"] = True
            trade["tp_level"] = 1
            be_price = round(trade["entry_price"] * 1.001, price_precision)
            trade["current_sl"] = be_price # Immediate BE
            force_update = True
            send_telegram_message(f"✅ *[{symbol}] TP1 HIT*\nSL moved to Break-Even (`{be_price}`). Triggering AI to determine TP3.")
            threading.Thread(target=expand_tp_targets, args=(symbol, current_price), daemon=True).start()
            
        # Check TP2
        if not trade.get("tp2_hit", False) and trade["best_price"] >= trade["tp_2"] and trade["tp_2"] > 0:
            trade["tp2_hit"] = True
            trade["tp_level"] = 2
            # Ladder SL to TP1
            ladder_sl = trade["tp_1"]
            trade["current_sl"] = ladder_sl
            force_update = True
            send_telegram_message(f"🚀 *[{symbol}] TP2 HIT*\nSL moved to TP1 level (`{ladder_sl}`). Searching for next targets.")
            threading.Thread(target=expand_tp_targets, args=(symbol, current_price), daemon=True).start()

        # Check subsequent TPs (Dynamic / Recovery expansion)
        curr_lvl = trade.get("tp_level", 0)
        if curr_lvl >= 1:
            next_tp_key = f"tp_{curr_lvl + 2}"
            if not trade.get(next_tp_key) and not trade.get("is_expanding"):
                print(f"[{symbol}] TP{curr_lvl} hit, but TP{curr_lvl + 2} missing. Asking AI.")
                trade["is_expanding"] = True
                threading.Thread(target=expand_tp_targets, args=(symbol, current_price), daemon=True).start()
            
            # Monitoring hitting the next dynamic TP
            next_tp_to_hit_key = f"tp_{curr_lvl + 1}"
            if trade.get(next_tp_to_hit_key) and trade["best_price"] >= trade[next_tp_to_hit_key]:
                trade["tp_level"] += 1
                prev_tp_key = f"tp_{trade['tp_level'] - 1}"
                ladder_sl = trade[prev_tp_key]
                trade["current_sl"] = ladder_sl
                force_update = True
                send_telegram_message(f"💰 *[{symbol}] TP{trade['tp_level']} HIT*\nSL moved to {prev_tp_key.upper()} level (`{ladder_sl}`).")
                trade["is_expanding"] = True
                threading.Thread(target=expand_tp_targets, args=(symbol, current_price), daemon=True).start()

    # V24.0: Manual SL trailing removed.
    # Native Bybit Trailing Stop is activated on order entry and handles SL natively.
    pass

_report_lock = threading.Lock()

def background_tasks():
    global GLOBAL_STATE, learn_data
    while True:
        try:
            now = time.time()
            now_dt = time.localtime()  # OPT v22.3.0: single call (was duplicated)
            # 8:00 AM (Central European Time) Daily Report
            if now_dt.tm_hour == 8 and GLOBAL_STATE['last_report_day'] != now_dt.tm_mday:
                if _report_lock.acquire(blocking=False):
                    try:
                        # Double-check after acquiring lock
                        if GLOBAL_STATE['last_report_day'] != now_dt.tm_mday:
                            GLOBAL_STATE['last_report_day'] = now_dt.tm_mday
                            learn_data['last_report_day'] = now_dt.tm_mday
                            save_learning_data(learn_data)
                            
                            # --- AI LESSON COMPRESSION (REINFORCEMENT LEARNING) ---
                            compression_msgs = []
                            if LESSON_EXTRACTOR_OK:
                                print("[BACKGROUND] Starting AI Lesson Compression...", flush=True)
                                for sym in SYMBOLS:
                                    msg = ai_lesson_extractor.compress_lessons_daily(sym)
                                    compression_msgs.append(msg)
                            
                            # Reload learning data after compression so report has fresh data
                            learn_data = load_learning_data()
                            
                            generate_master_daily_report(compression_summary="\n".join(compression_msgs))
                            GLOBAL_STATE['last_report_hour'] = now_dt.tm_hour
                    finally:
                        _report_lock.release()

            # Automatic Nexus Update (Hourly)
            if now_dt.tm_hour != GLOBAL_STATE['last_nexus_hour']:
                if NEXUS_WORKER_AVAILABLE:
                    print(f"[BACKGROUND] Starting Hourly Nexus Intelligence Update...", flush=True)

                    # ---> ADDING GMAIL MODULE HERE <---
                    try:
                        print("[GMAIL BRIDGE] Checking for new macro reports on Gmail...", flush=True)
                        gmail_intel_bridge.extract_intel_from_gmail()
                    except Exception as e:
                        print(f"[GMAIL BRIDGE] Error: {e}", flush=True)
                    # ------------------------------------

                    # Running in a separate thread to avoid blocking background_tasks (though Gemini Flash is fast)
                    threading.Thread(target=ai_nexus_worker.update_nexus, daemon=True).start()
                    GLOBAL_STATE['last_nexus_hour'] = now_dt.tm_hour

                    # [v22.8] Cyclic DB cleanup: closing ghosts every hour
                    if BOT_MEMORY_OK:
                        threading.Thread(target=run_periodic_db_sync, daemon=True).start()
                # Periodic Time Sync
                sync_server_time()
                
            # Macro Pulse: Checking the market every 60 minutes regardless of events (v21.13.2)
            # [v23.4] MISSION CHECK: Checking test missions every minute
            nexus_state = load_nexus_state()
            test_action_raw = nexus_state.get('test_action', "NONE:NONE")

            for symbol in SYMBOLS:
                # Test mission trigger (Priority)
                if ":" in test_action_raw and not GLOBAL_STATE.get('test_executed', False):
                    t_sym, _ = test_action_raw.split(":")
                    if symbol == t_sym:
                        print(f"[{symbol}] BACKGROUND: Test mission detected. Triggering immediate evaluation.", flush=True)
                        if GLOBAL_STATE['klines_cache'][symbol]:
                             last_p = GLOBAL_STATE['klines_cache'][symbol][-1]['close']
                             threading.Thread(target=evaluate_market_condition, args=(symbol, last_p), daemon=True).start()

                # [v21.13.2] Reduced from 4h to 1h for better bot "learning"
                if GLOBAL_STATE['open_trades'][symbol]['active']:
                    continue # Skip forced pulse for active trades to prevent AI early exits

                if now - GLOBAL_STATE['last_ai_call'][symbol] > 3600:
                    print(f"[{symbol}] FORCED PULSE: No events for 60m. Forcing evaluation for data recording.", flush=True)
                    GLOBAL_STATE['last_ai_call'][symbol] = now
                    if GLOBAL_STATE['klines_cache'][symbol]:
                        last_price = GLOBAL_STATE['klines_cache'][symbol][-1]['close']
                        threading.Thread(target=evaluate_market_condition, args=(symbol, last_price), daemon=True).start()

            if GLOBAL_STATE['listen_key']:
                keepalive_listen_key()
        except Exception as e:
            print(f"Background thread error: {e}", flush=True)
        time.sleep(60) # Check every minute for PULSE precision

import queue
WSS_QUEUE = queue.Queue()

def wss_worker():
    while True:
        try:
            ws, message = WSS_QUEUE.get()
            process_message(ws, message)
            WSS_QUEUE.task_done()
        except Exception as e:
            print(f"[WSS WORKER ERROR] {e}")

threading.Thread(target=wss_worker, daemon=True).start()

def on_message(ws, message):
    WSS_QUEUE.put((ws, message))

def process_message(ws, message):
    global GLOBAL_STATE
    try:
        data = json.loads(message)
    except: return
    
    # Bybit V5 Public/Private uses 'topic'
    topic = data.get("topic", "")
    data_list = data.get("data", [])
    
    if "kline" in topic:
        symbol = topic.split(".")[-1]
        if symbol not in GLOBAL_STATE['klines_cache'] or not data_list: return
        
        k = data_list[0]
        current_price = float(k['close'])
        if GLOBAL_STATE['last_ai_price'][symbol] == 0:
            GLOBAL_STATE['last_ai_price'][symbol] = current_price
            
        live_candle = {"close": current_price, "high": float(k['high']), "low": float(k['low']), "open": float(k['open'])}
        
        if GLOBAL_STATE['klines_cache'][symbol] and not GLOBAL_STATE['klines_cache'][symbol][-1].get("is_closed", False):
            GLOBAL_STATE['klines_cache'][symbol][-1] = live_candle
        else:
            GLOBAL_STATE['klines_cache'][symbol].append(live_candle)
            if len(GLOBAL_STATE['klines_cache'][symbol]) > 500:
                GLOBAL_STATE['klines_cache'][symbol].pop(0)
        
        if k.get('confirm'):
            GLOBAL_STATE['klines_cache'][symbol][-1]["is_closed"] = True
            
        # Heartbeat
        GLOBAL_STATE['msg_counter'][symbol] += 1
        if GLOBAL_STATE['msg_counter'][symbol] % 300 == 0:
            prices = [kl['close'] for kl in GLOBAL_STATE['klines_cache'][symbol]]
            if len(prices) > 20:
                current_rsi = calculate_rsi(prices, 14)
                print(f"[{symbol}] BYBIT HEARTBEAT: Price: {current_price:.2f} | RSI: {current_rsi:.2f}", flush=True)

        # Trailing Stop update (MOVE TO THREAD TO PREVENT WSS BLOCK)
        if GLOBAL_STATE['open_trades'][symbol]["active"]:
             def bg_update_ts(sym, price):
                 try:
                     learn_data = load_learning_data()
                     params = learn_data.get("parameters", {}).get(sym, {})
                     if params and len(GLOBAL_STATE['klines_cache'][sym]) > params.get('atr_period', 14):
                         atr = calculate_atr(GLOBAL_STATE['klines_cache'][sym], params['atr_period'])
                         update_trailing_stop(sym, price, params, atr)
                 except Exception as e:
                     print(f"[BG TS ERROR] {sym}: {e}")
             
             threading.Thread(target=bg_update_ts, args=(symbol, current_price), daemon=True).start()

    elif topic == "position":
        for pos in data_list:
            symbol = pos['symbol']
            if symbol in SYMBOLS:
                qty = abs(float(pos['size']))
                if qty == 0:
                    if GLOBAL_STATE['open_trades'].get(symbol, {}).get("active", False):
                        print(f"[{symbol}] Bybit: Position fully CLOSED. Cleaning up.")
                        cancel_all_orders(symbol)
                        
                        def bg_close_handler(sym, s):
                            try:
                                report_closed_position(sym, s)
                                if BOT_MEMORY_OK:
                                    _mem_tid = GLOBAL_STATE['open_trades'][sym].get("memory_trade_id")
                                    pnl_data = bybit.get_closed_pnl(sym, limit=1)
                                    real_pnl = float(pnl_data[0].get('realizedPnl', 0.0)) if pnl_data else 0.0
                                    exit_p = float(pnl_data[0].get('exit_price', pnl_data[0].get('avgExitPrice', 0.0))) if pnl_data else 0.0
                                    bot_memory.save_trade_close(sym, exit_p, real_pnl, "WSS Bybit qty=0", _mem_tid)
                                    # Trigger lesson extraction for every closed trade
                                    if LESSON_EXTRACTOR_OK and _mem_tid:
                                        ai_lesson_extractor.trigger_lesson_extraction(_mem_tid)
                                    # Update Circuit Breaker
                                    if CIRCUIT_BREAKER_OK:
                                        trade_side = GLOBAL_STATE['open_trades'][sym].get('side', s)
                                        if real_pnl > 0:
                                            circuit_breaker.record_win(sym, trade_side)
                                        elif real_pnl < 0:
                                            circuit_breaker.record_loss(sym, trade_side)
                            except Exception as _me: print(f"[BG CLOSE ERROR] {sym}: {_me}")

                        side = GLOBAL_STATE['open_trades'][symbol].get("side", "UNKNOWN")
                        threading.Thread(target=bg_close_handler, args=(symbol, side), daemon=True).start()

                        GLOBAL_STATE['open_trades'][symbol]["active"] = False
                        GLOBAL_STATE['open_trades'][symbol]["algo_id"] = None
                else:
                    # Update local state
                    if symbol in GLOBAL_STATE['open_trades']:
                        trade = GLOBAL_STATE['open_trades'][symbol]
                        trade["active"] = True
                        if abs(trade.get("qty", 0) - qty) > 1e-9:
                            trade["qty"] = qty
                            trade["force_sl_update"] = True

def on_error(ws, error):
    import traceback
    print(f"WebSocket Error: {error}", flush=True)
    traceback.print_exc()

def get_swing_points(klines, depth=5):
    """
    Identifies local peaks and troughs (Pivots) for Elliott Wave structure analysis.
    depth: how many candles on both sides must be lower/higher to confirm the point.
    """
    swings = []
    if len(klines) < depth * 2 + 1:
        return swings

    for i in range(depth, len(klines) - depth):
        current_high = klines[i]['high']
        current_low = klines[i]['low']
        
        # Checking Peak
        is_peak = True
        for j in range(i - depth, i + depth + 1):
            if i == j: continue
            if klines[j]['high'] > current_high:
                is_peak = False
                break
        
        if is_peak:
            swings.append({"type": "PEAK", "price": current_high, "time": klines[i].get('time', i)})
            continue

        # Checking Trough
        is_trough = True
        for j in range(i - depth, i + depth + 1):
            if i == j: continue
            if klines[j]['low'] < current_low:
                is_trough = False
                break
        
        if is_trough:
            swings.append({"type": "TROUGH", "price": current_low, "time": klines[i].get('time', i)})

    # Returning only the last 12 points to keep the prompt concise
    return swings[-12:]

def get_dynamic_leverage(symbol, nexus_score, fgi_score, adx, suggested_leverage):
    """
    V21.5: Dynamic Leverage Scaling.
    Adjusts suggested leverage based on Nexus Score, Fear & Greed, and Market Regime.
    """
    # 1. Base filter: Nexus Score
    # Score < 5.0 reduces leverage proportionally
    nexus_multiplier = min(1.0, nexus_score / 7.0) 
    
    # 2. Risk filter: Extreme FGI
    fgi_multiplier = 1.0
    if fgi_score < 20 or fgi_score > 80:
        fgi_multiplier = 0.5 # Half leverage in extreme panic/euphoria

    # 3. Regime filter: ADX
    regime_cap = 20
    if adx < 20: # RANGING/CHOP
        regime_cap = 5 # Strict cap for ranging markets
    
    final_leverage = int(round(suggested_leverage * nexus_multiplier * fgi_multiplier))
    final_leverage = max(1, min(final_leverage, regime_cap))
    
    print(f"[{symbol}] DYNAMIC LEVERAGE: Suggested {suggested_leverage}x -> Final {final_leverage}x (Nexus: {nexus_score}, FGI: {fgi_score}, ADX: {adx:.1f})")
    return final_leverage

def get_dynamic_risk_multiplier():
    """Returns position size multiplier based on Nexus Score"""
    try:
        with open('nexus_state.json', 'r') as f:
            data = json.load(f)
            score = data.get('nexus_score', 5.0)
            
        # Multiplier logic (Base is 1.0 for score 5.0)
        multiplier = 1.0
        if score >= 8.5: multiplier = 2.0  # Very confident setup - risk 2x more
        elif score >= 7.0: multiplier = 1.5  # Good setup - risk 1.5x more
        elif score <= 3.0: multiplier = 0.2  # Extreme risk - risk only 20% of base
        elif score <= 4.5: multiplier = 0.5  # Uncertainty - risk half
        
        return multiplier
    except:
        return 0.5 # Fail-safe

def run_periodic_db_sync(tag="HOURLY"):
    """[v22.8] Cyclic synchronization of SQLite DB with exchange.
    Closes 'ghosts' — records in DB marked as open,
    but whose position on the exchange no longer exists.
    Does not use Gemini API (zero tokens)."""
    if not BOT_MEMORY_OK:
        return
    try:
        actual_open_symbols = set(GLOBAL_STATE.get('open_trades', {}).keys())
        open_db_trades = bot_memory.get_open_trades_from_db()

        sync_count = 0
        for db_trade in open_db_trades:
            sym = db_trade['symbol']
            if sym not in actual_open_symbols:
                print(f"[{tag} SYNC] Ghost {sym} detected in DB. Fetching closed PnL from Bybit...", flush=True)
                pnl_data = bybit.get_closed_pnl(sym, limit=5)
                if pnl_data:
                    p = pnl_data[0]
                    exit_price = float(p['avgExitPrice'])
                    realized_pnl = float(p.get('realizedPnl', p.get('closedPnl', 0.0)))
                    bot_memory.save_trade_close(sym, exit_price, realized_pnl, f"Cleaned ({tag} Sync)", db_trade['id'])
                    sync_count += 1
                else:
                    bot_memory.save_trade_close(sym, 0.0, 0.0, f"Ghosted ({tag} Sync)", db_trade['id'])
                    sync_count += 1
                time.sleep(0.5)

        if sync_count > 0:
            print(f"[{tag} SYNC] Fixed {sync_count} ghosts in DB.", flush=True)
    except Exception as e:
        print(f"[{tag} SYNC] Error: {e}", flush=True)

def export_dashboard_state():
    """[v22.8.1] Exports current wallet state (balance, positions) to nexus_state.json.
    This ensures the Dashboard always shows current data, even if the AI engine hasn't updated."""
    try:
        base_path = os.path.dirname(os.path.abspath(__file__))
        nexus_path = os.path.join(base_path, 'nexus_state.json')

        # Load existing data to preserve AI data (Score, Comment)
        current_nexus_data = {}
        if os.path.exists(nexus_path):
            try:
                with open(nexus_path, 'r', encoding='utf-8') as f:
                    current_nexus_data = json.load(f)
            except: pass

        # Updating only trading data
        balance_info = get_balance()
        current_nexus_data["balance"] = balance_info.get('wallet', 0.0)
        current_nexus_data["open_trades"] = GLOBAL_STATE.get('open_trades', {})
        current_nexus_data["last_update"] = time.time()

        with open(nexus_path, 'w', encoding='utf-8') as f:
            json.dump(current_nexus_data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[DASHBOARD] State export error: {e}", flush=True)
        return False

def evaluate_market_condition(symbol, current_price):
    global GLOBAL_STATE, learn_data
    if not SYMBOL_LOCKS[symbol].acquire(blocking=False):
        return

    try:
        # --- 1. STATE SYNCHRONIZATION (Balance and positions only) ---
        export_dashboard_state()


        # --- 2. YOUR RAM CALCULATIONS (Pure logic) ---
        params = learn_data.get("parameters", {}).get(symbol, {})
        if not params: return

        # [v23.4] Modification for test mission
        is_test_mission = (":" in load_nexus_state().get('test_action', "") and not GLOBAL_STATE.get('test_executed', False))
        
        klines = GLOBAL_STATE['klines_cache'].get(symbol, [])
        if not is_test_mission and len(klines) < params.get('ema_period', 200) + 10: 
            return
        
        # If test mission and no klines, create dummy kline for price
        if is_test_mission and not klines:
            klines = [{'close': current_price}]

        prices = [k['close'] for k in klines]
        ema = calculate_ema(prices, params['ema_period'])
        rsi = calculate_rsi(prices, params['rsi_period'])
        atr = calculate_atr(klines, params.get('atr_period', 14))
        adx = calculate_adx(klines, params.get('adx_period', 14))

        # === 4-STATE MARKET REGIME CLASSIFIER ===
        # Uses ADX (trend strength), ATR vs historical ATR (volatility), EMA (direction)
        # States: TREND_UP | TREND_DOWN | RANGE_BOUND | VOLATILE_CHOP
        try:
            # Historical ATR baseline (last 50 bars vs last 14)
            atr_long = calculate_atr(klines, min(50, len(klines) - 1)) if len(klines) > 15 else atr
            atr_ratio = atr / atr_long if atr_long > 0 else 1.0  # > 1.3 = elevated volatility

            # Bollinger Band Width (proxy for squeeze/expansion)
            if len(prices) >= 20:
                bb_mean = sum(prices[-20:]) / 20
                bb_std = (sum((p - bb_mean) ** 2 for p in prices[-20:]) / 20) ** 0.5
                bb_width = (4 * bb_std) / bb_mean if bb_mean > 0 else 0  # normalized BB width
            else:
                bb_width = 0.02  # default

            trending = adx >= 22
            volatile = atr_ratio > 1.35 or bb_width > 0.04
            bullish = current_price > ema

            if not trending and volatile:
                market_regime = "VOLATILE_CHOP"   # no direction + high volatility = true chop — stay out
            elif trending and bullish:
                market_regime = "TREND_UP"
            elif trending and not bullish:
                market_regime = "TREND_DOWN"
            else:
                market_regime = "RANGE_BOUND"     # ADX < 22, low volatility — no clear direction

            print(
                f"[{symbol}] REGIME: {market_regime} "
                f"(ADX={adx:.1f}, ATR_ratio={atr_ratio:.2f}, BB_width={bb_width:.3f})",
                flush=True
            )
        except Exception as _re:
            # Fallback to legacy binary regime
            market_regime = "TREND_UP" if current_price > ema else "TREND_DOWN"
            print(f"[{symbol}] REGIME FALLBACK: {market_regime} ({_re})", flush=True)


        # V21.9.0 DEEP LOCKDOWN: Physically prevents entry if inside 60m Anti-Churn window.
        now = time.time()
        time_since_close = now - GLOBAL_STATE.get('last_close_time', {}).get(symbol, 0)
        if time_since_close < 1800:
            remaining = int((1800 - time_since_close) / 60)
            print(f"[{symbol}] ANTI-CHURN LOCKOUT: Entry blocked for {remaining} more minutes.", flush=True)
            return

        bal_data = get_balance()
        wallet_bal = bal_data['wallet']
        available = bal_data['available']
        if wallet_bal <= 0: return

        risk_mult = get_dynamic_risk_multiplier()
        risk_amount = wallet_bal * RISK_PERCENT * risk_mult
        
        # Safety check for available margin
        if risk_amount > available:
            print(f"[RISK] Risk amount {risk_amount:.2f} exceeds available margin {available:.2f}. Capping.")
            risk_amount = available
        
        # Log the dynamic risk usage
        if risk_mult != 1.0:
            print(f"[RISK] Applying multiplier {risk_mult}x based on Nexus Score. Base risk amount: {wallet_bal * RISK_PERCENT:.2f} -> Dynamic: {risk_amount:.2f} USDT")
        learn_data = load_learning_data()
        nexus_state = load_nexus_state()
        fgi_score = get_fear_greed_index()
        
        # [v23.4] MISSION: FUNCTIONAL TEST HANDLER
        test_action_raw = nexus_state.get('test_action', "NONE:NONE")
        is_test_mission = False
        if ":" in test_action_raw and not GLOBAL_STATE.get('test_executed', False):
            t_sym, t_side = test_action_raw.split(":")
            if symbol == t_sym:
                print(f"[{symbol}] !!! MISSION TRIGGERED: FUNCTIONAL TEST ({t_side}) !!!", flush=True)
                is_test_mission = True
                GLOBAL_STATE['test_executed'] = True 
                print(f"[{symbol}] DEBUG MISSION: variables set. Proceeding to evaluation logic.", flush=True)
                
                # Setting test parameters
                ai_action = 'LONG' if t_side == 'LONG' else 'SHORT'
                ai_reason = "FORCED DICTATOR FUNCTIONALITY TEST"
                ai_scale = 1.0
                ai_leverage = 2
                suggested_leverage = 2
                
                # Tight TP/SL (1%)
                price_prec = get_price_precision(symbol)
                qty_prec = get_symbol_precision(symbol)
                ai_sl = round(current_price * (0.99 if ai_action == 'LONG' else 1.01), price_prec)
                ai_tp = round(current_price * (1.01 if ai_action == 'LONG' else 0.99), price_prec)
                
                # Volume approx 12 USDT
                risk_amount = 12.0 / ai_leverage
                
                # Auto-close function after 60 seconds
                def auto_close_test(sym):
                    time.sleep(60)
                    print(f"[{sym}] TEST MISSION: Auto-closing position for cleanup...", flush=True)
                    t_info = GLOBAL_STATE['open_trades'].get(sym, {})
                    if t_info.get("active"):
                        e_side = 'SELL' if t_info['side'] == 'BUY' else 'BUY'
                        cancel_all_orders(sym)
                        order_res = place_market_order(sym, e_side, t_info['qty'], reduce_only=True)
                        t_info["active"] = False
                        
                        # [v23.4] LOG CLOSE TO DB
                        if BOT_MEMORY_OK:
                            try:
                                t_id = t_info.get("memory_trade_id")
                                pnl = 0 # In the test we do not calculate precisely
                                bot_memory.save_trade_close(symbol=sym, exit_price=current_price, pnl=pnl, close_reason="Test Mission Timeout", trade_id=t_id)
                            except: pass
                            
                        send_telegram_message(f"🏁 *[{sym}] TEST MISSION COMPLETED*\nPosition closed automatically.")
                
                threading.Thread(target=auto_close_test, args=(symbol,), daemon=True).start()
        
        if not is_test_mission:
            nexus_score = nexus_state.get('nexus_score', 5.0)
            autonomy_hint = f"\n> [CONTEXT] Market Nexus Score is {nexus_score}. Use this as macro guidance alongside technical structure."
        else:
            nexus_score = 5.0 # Neutral for test
            autonomy_hint = "TEST MODE ACTIVE"
        
        if GLOBAL_STATE['open_trades'].get(symbol, {}).get("active", False): 
            print(f"[{symbol}] Trade active. Skipping AI re-evaluation per user request (Autonomous TP/SL management).", flush=True)
            return
        else:
            # 2. Backup API check (only if locally no position)
            if check_open_positions(symbol): return
            if check_open_orders(symbol):
                cancel_all_orders(symbol)
                return

        
        # Liquidity Sweep (SFP)
        sfp_signal = detect_sfp(klines)
        
        # Market Symmetry (BTC/ETH Sync)
        symmetry = get_market_symmetry()
        symmetry_desc = "BULLISH SYNC" if symmetry == 1 else "BEARISH SYNC" if symmetry == -1 else "DIVERGENCE"

        macro_klines = get_klines(symbol, MACRO_INTERVAL, limit=params['ema_period'] + 10)
        macro_trend_bullish = True
        macro_ema = 0
        if macro_klines:
             macro_prices = [k['close'] for k in macro_klines]
             macro_ema = calculate_ema(macro_prices, params['ema_period'])
             macro_trend_bullish = macro_prices[-1] > macro_ema

        # --- V12.3: Multi-TF Resonance (1H Data) ---
        klines_1h = get_klines(symbol, "1h", limit=params['ema_period'] + 10)
        ema_1h = 0
        rsi_1h = 50
        if klines_1h:
            prices_1h = [k['close'] for k in klines_1h]
            ema_1h = calculate_ema(prices_1h, params['ema_period'])
            rsi_1h = calculate_rsi(prices_1h, params['rsi_period'])

        # External signal from Telegram channel
        channel_signal_text = "No data (reader inactive)"
        if TG_READER_AVAILABLE:
            sig = telegram_reader.get_recent_signal(symbol, max_age_seconds=3600)
            if sig:
                dir_str = "LONG BIAS" if sig["direction"] == 1 else "SHORT BIAS"
                channel_signal_text = f"{dir_str} (strength: {sig['strength']:.0%}) – message from {int((time.time()-sig['timestamp'])/60)}min ago"
            else:
                channel_signal_text = "No signal in the last hour"

        # Structural Price Action, MACD and Divergences
        structure_desc = analyze_price_action_structure(klines, depth=3)
        macd_data = calculate_macd([float(k['close']) for k in klines])
        divergence_signal = detect_divergences(klines)

        # Structural Macro Memory
        # V21.10.0: Elliott Wave TTL - expire context older than 4 hours
        raw_macro_context = learn_data.get("macro_map", {}).get(symbol, "No prior analysis (new cycle).")
        macro_map_age = time.time() - learn_data.get("macro_map_updated", {}).get(symbol, 0)
        if macro_map_age > 14400:  # 4 hours
            macro_context = f"[EXPIRED - {int(macro_map_age/3600)}h old] Perform fresh wave analysis. Do NOT rely on prior context."
            print(f"[{symbol}] Wave context expired ({macro_map_age/3600:.1f}h old). Forcing fresh analysis.", flush=True)
        else:
            macro_context = raw_macro_context

        # Order Book Impact Analysis
        order_book_impact = get_order_book_imbalance(symbol, current_price, threshold_pct=0.01)
        
        # Orderflow Metrics (V24.0: Funding Rate & CVD)
        orderflow = bybit.get_orderflow_metrics(symbol)
        funding_rate = orderflow['funding_rate']
        cvd = orderflow['cvd']

        # Trade History Context for AI
        symbol_history = []
        if os.path.exists('engine_trades.log'):
            with open('engine_trades.log', 'r') as f:
                lines = f.readlines()
                for line in reversed(lines):
                    if f"CLOSED {symbol}" in line or f"LOG {symbol}" in line:
                        symbol_history.append(line.strip())
                        if len(symbol_history) >= 3: break
        symbol_history_str = "\n".join(symbol_history)

        active_positions = []
        for sym in SYMBOLS:
            tt = GLOBAL_STATE['open_trades'].get(sym, {})
            if tt.get("active", False):
                active_positions.append(f"{sym}: {tt['side']} (Entry: {tt['entry_price']})")
        portfolio_summary = ", ".join(active_positions) if active_positions else "NONE"

        active_trade_str = "NONE"
        is_revaluation = False
        if GLOBAL_STATE['open_trades'].get(symbol, {}).get("active", False):
            is_revaluation = True
            t = GLOBAL_STATE['open_trades'][symbol]
            entry_p = t.get('entry_price', 0) or 0
            pnl_pct = 0.0
            if entry_p > 0:
                is_buy = str(t.get('side', '')).upper() in ['BUY', 'LONG']
                pnl_pct = ((current_price - entry_p) / entry_p * 100) if is_buy else ((entry_p - current_price) / entry_p * 100)
            
            active_trade_str = f"SIDE: {t.get('side')} | ENTRY: {entry_p} | SL: {t.get('current_sl')} | CURRENT PnL: {pnl_pct:.2f}%"

        # --- [v23.4] AI DECISION OR TEST MISSION ---
        decision = None
        if is_test_mission:
            print(f"[{symbol}] BYPASSING AI: Test Mission Active. Using predetermined parameters.", flush=True)
            decision = {
               "action": ai_action,
               "reason": ai_reason,
               "sl_price": ai_sl,
               "tp_price": ai_tp,
               "scale": ai_scale,
               "leverage": ai_leverage,
               "wave_analysis": "FUNCTIONAL TEST CYCLE"
            }
        else:
            print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] WSS TRIGGER: {symbol} (Cena: {current_price:.2f} | RSI: {rsi:.2f} | Regime: {market_regime}) | Pytam AI...", flush=True)
            GLOBAL_STATE['last_ai_call'][symbol] = time.time()
            GLOBAL_STATE['last_ai_price'][symbol] = current_price
            
            ai_lessons_text = "No historical lessons for this instrument."
            if BOT_MEMORY_OK:
                # Pass current regime so memory returns regime-matched lessons first
                recent_lessons = bot_memory.get_recent_lessons(symbol, limit=5, current_regime=market_regime)
                if recent_lessons:
                    regime_matched = [l for l in recent_lessons if market_regime in l.get('rule_if', '')]
                    rules_str = "\n".join([
                        f"  [{i+1}]{'★ REGIME MATCH' if market_regime in l.get('rule_if','') else ''} ONLY IF: {l['rule_if']}\n       → THEN: {l['rule_then']}\n       WHY: {l['rule_because']}"
                        for i, l in enumerate(recent_lessons)
                    ])
                    ai_lessons_text = (
                        f"CONDITIONAL LESSONS — pre-filtered for current regime '{market_regime}' ({len(regime_matched)}/{len(recent_lessons)} are direct matches, marked ★):\n"
                        f"{rules_str}\n"
                        f"★ REGIME MATCH lessons are HIGHLY RELEVANT — current conditions match them directly. Treat them as strong signals."
                    )
        
            # Calculate basic ATR references for the prompt (as guidelines, not strict limits)
            atr_ref_sl_wide = atr * 2.5
            
            # --- OVEREXTENSION LOGIC ---
            ema_distance_atr = (current_price - ema) / atr if atr > 0 else 0
            is_overextended_long = ema_distance_atr > 2.0
            is_overextended_short = ema_distance_atr < -2.0
            
            overextension_warning = ""
            if is_overextended_long:
                overextension_warning = f"⚠️ OVEREXTENDED UPWARDS: Price is +{ema_distance_atr:.2f} ATR above 15m EMA! DANGER: High probability of mean-reversion pullback."
            elif is_overextended_short:
                overextension_warning = f"⚠️ OVEREXTENDED DOWNWARDS: Price is {ema_distance_atr:.2f} ATR below 15m EMA! DANGER: High probability of mean-reversion pullback."
            
            if market_regime == "VOLATILE_CHOP":
                rm_guideline = f"Market is CHOPPY. If you must trade, use a wider SL (e.g. ~{atr_ref_sl_wide:.4f} distance) and scale down."
            else:
                rm_guideline = f"Standard ATR is {atr:.4f}. You have full autonomy to place SL behind structural wicks (SFP) or recent swings."

            # --- INTENT MEMORY ---
            intent_memory = learn_data.get("intent_memory", {}).get(symbol, "")
            intent_str = f"🎯 ACTIVE PLAN (CONTINUITY): {intent_memory}\n" if intent_memory else ""

            # --- MULTI-TF EMA EXTENSIONS ---
            ema_1h_distance_atr = (current_price - ema_1h) / atr if atr > 0 else 0
            macro_ema_distance_atr = (current_price - macro_ema) / atr if atr > 0 else 0

            prompt = f"""You are Antigravity AI {version.FULL_VERSION}. {autonomy_hint}
{intent_str}

╔══════════════════════════════════════════════════════╗
║  PRIME DIRECTIVE: MAKE MONEY. PROTECT CAPITAL.      ║
╚══════════════════════════════════════════════════════╝

Your SOLE purpose is to generate consistent, compounding profit on the Bybit exchange.
Every decision you make must be evaluated through one lens: "Will this increase the account balance?"
- A HOLD when conditions are unclear IS profit (preserved capital).
- A bad trade IS a loss, even if the reasoning seemed logical.
- You have learned from {len(bot_memory.get_recent_lessons(symbol, limit=100) if BOT_MEMORY_OK else [])} past trades on {symbol}. USE that knowledge.

═══════════════════════════════════════════════════════
CRITICAL HARD FILTERS (KILL-SWITCHES) — NON-NEGOTIABLE:
You MUST return "action": "HOLD" and abort the trade if ANY of the following are true:
1. CHOP / WEAK TREND: If Regime is 'VOLATILE_CHOP' OR ('RANGE_BOUND' and ADX < 20) -> RETURN HOLD.
2. LESSON OVERRIDE: If any CONDITIONAL LESSON (★ REGIME MATCH) says "AVOID LONG" and you consider LONG -> RETURN HOLD. Same for SHORT.
3. ORDER BOOK / CVD CONTRADICTION: If considering LONG but Order Book Imbalance is 'ASKS', or considering SHORT but 'BIDS' -> RETURN HOLD.
4. NO CHASING (OVEREXTENSION): If considering LONG but price is OVEREXTENDED UPWARDS, or considering SHORT but OVEREXTENDED DOWNWARDS -> RETURN HOLD. Do not buy the top or short the bottom!

You have access to the following intelligence sources — use ALL of them:
  1. ELLIOTT WAVE: structural market geometry, wave position, expected next move
  2. MARKET REGIME + ADX: is there a real trend? (ADX < 20 = chop, avoid new entries)
  3. RSI: momentum state, divergences, extreme levels
  4. SFP (Swing Failure Pattern): liquidity sweeps — high-probability reversal signals
  5. BTC/ETH SYMMETRY: cross-asset confirmation — divergence is a warning sign
  6. NEXUS AI SCORE: macro sentiment from news, video analysis, Fear&Greed
  7. CONDITIONAL LESSONS: your own learned patterns from closed trades
  8. ORDERFLOW (CVD/Funding): pure buying/selling pressure metrics

═══════════════════════════════════════════════════════
PORTFOLIO STATE:
- Active Trades: {portfolio_summary}
- Cross-symbol rule: Avoid contradictions (e.g., LONG ETH + SHORT BTC) UNLESS you have strong evidence of decoupling.

═══════════════════════════════════════════════════════
INSTRUMENT: {symbol}

MARKET STRUCTURE & MOMENTUM (15m):
- Wave Context (Macro): {macro_context}
- Local Structure: {structure_desc}
- MACD Momentum: {macd_data['hist_slope']} (MACD: {macd_data['macd']:.4f}, Signal: {macd_data['signal']:.4f})
- Divergence: {divergence_signal}

QUANTITATIVE METRICS:
- Regime: {market_regime} | ADX: {adx:.2f} {"⚠️ WEAK TREND - be cautious with new entries" if adx < 20 else "✅ TREND CONFIRMED"}
- SFP Signal: {sfp_signal if sfp_signal else 'None'} {"← HIGH CONVICTION reversal signal" if sfp_signal else ""}
- BTC/ETH Sync: {symmetry_desc}
- Order Book Imbalance: {order_book_impact}
- Orderflow Data: CVD (last 500 trades) = {cvd:.2f} ({"Bullish" if cvd > 0 else "Bearish"}), Funding Rate = {funding_rate:.6f}

TECHNICAL ANALYSIS — MULTI-TIMEFRAME:

[15m — Entry Timeframe]
- Price: {current_price:.4f} | RSI: {rsi:.2f} {"⚠️ OVERSOLD" if rsi < 30 else "⚠️ OVERBOUGHT" if rsi > 70 else "✅ Neutral"} | ATR: {atr:.4f}
- EMA({params['ema_period']}): {ema:.4f} {"↑ price ABOVE EMA (bullish 15m)" if current_price > ema else "↓ price BELOW EMA (bearish 15m)"}
- EMA Extension: {ema_distance_atr:.2f} ATR distance from EMA. {overextension_warning}
- Regime: {market_regime} | ADX: {adx:.2f} {"⚠️ WEAK TREND — avoid new entries" if adx < 20 else "✅ TREND CONFIRMED"}

[1H — Swing Context]
- EMA(1H): {ema_1h:.4f} {"↑ bullish 1H trend" if current_price > ema_1h > 0 else "↓ bearish 1H trend" if ema_1h > 0 else "N/A"}
- 1H EMA Extension: {ema_1h_distance_atr:.2f} ATR
- RSI(1H): {rsi_1h:.2f} {"⚠️ OVERSOLD 1H" if rsi_1h < 35 else "⚠️ OVERBOUGHT 1H" if rsi_1h > 65 else ""}

[4H — Macro Structure]
- EMA(4H): {macro_ema:.4f} {"↑ MACRO BULLISH (price > 4H EMA)" if macro_trend_bullish else "↓ MACRO BEARISH (price < 4H EMA)"}
- 4H EMA Extension: {macro_ema_distance_atr:.2f} ATR

[Multi-TF Alignment]
{"✅ ALL BULLISH — 15m+1H+4H aligned UP: strong LONG confirmation" if (current_price > ema and current_price > ema_1h and macro_trend_bullish) else "🔴 ALL BEARISH — 15m+1H+4H aligned DOWN: strong SHORT confirmation" if (current_price < ema and current_price < ema_1h and not macro_trend_bullish) else "⚠️ MIXED TIMEFRAMES — DO NOT force a trade, wait for alignment or rely on strongest signal"}
* COUNTER-TREND SCALPING: If the market is severely OVEREXTENDED, you are PERMITTED to open a counter-trend MEAN-REVERSION trade (e.g. LONG in a BEARISH macro) if SFP or divergence is present. Target the 15m EMA as Take Profit.
* REVERSAL CONFIRMATION: If executing a pullback strategy, verify if CVD (Orderflow) confirms the rejection (e.g. positive CVD on bottom).

NEXUS INTELLIGENCE:
- Macro Bias: {nexus_state.get('macro_bias', 'NEUTRAL')} | Score: {nexus_state.get('nexus_score', 5.0)}/10
  {"→ Strong bullish macro — favor LONGs, be cautious with SHORTs" if nexus_state.get('nexus_score', 5.0) >= 7 else "→ Strong bearish macro — favor SHORTs, be cautious with LONGs" if nexus_state.get('nexus_score', 5.0) <= 3 else "→ Neutral/mixed macro — rely more on technical structure"}

═══════════════════════════════════════════════════════
YOUR MEMORY (CONDITIONAL LESSONS):
{ai_lessons_text}

═══════════════════════════════════════════════════════
ACTIVE POSITION ON {symbol}:
{active_trade_str}

═══════════════════════════════════════════════════════
RISK MANAGEMENT — HARD RULES:
- ⚠️ SL MUST be at least {atr * 2.0:.4f} (2.0 ATR) away from entry. NEVER place SL closer than this. Tight SLs result in premature exits on noise/wicks. If your structural level is tighter than 2.0 ATR, DO NOT take the trade.
- TP MUST give a Risk:Reward ratio of at least 2.0. If R:R < 2.0, DO NOT take the trade.
- {rm_guideline}
- Recommended SL placement: behind the most recent swing low/high or SFP wick, typically 1.5–2.5x ATR from entry.
- Recommended TP placement: at the next structural resistance/support, typically 2.0–4.0x ATR from entry.
- `scale`: 0.3-0.5 for uncertain setups, 0.7-1.0 for high confluence.
- Leverage: 3-5x default, 7x MAXIMUM only for SFP-confirmed high-conviction setups. (Note: System will dynamically scale this down based on risk factors).
- HOLD is a valid and often optimal action — do NOT force trades in ambiguous conditions.

Output JSON: {{"action": "LONG/SHORT/HOLD/EXIT", "sl_price": float, "tp_price": float, "scale": 0.1-1.0, "leverage": int, "wave_analysis": "short_desc", "reason": "string"}}
"""
            try:
                cache_key = f"{symbol}_reevaluation" if is_revaluation else f"{symbol}_evaluation"
                response_text = ai_gateway.generate_content(
                    prompt=prompt, response_mime='application/json', cache_key=cache_key, cooldown=300
                )
                if response_text:
                    decision = json.loads(response_text)
                    if "wave_analysis" in decision:
                        if "macro_map" not in learn_data: learn_data["macro_map"] = {}
                        if "macro_map_updated" not in learn_data: learn_data["macro_map_updated"] = {}
                        learn_data["macro_map"][symbol] = decision["wave_analysis"]
                        learn_data["macro_map_updated"][symbol] = time.time()
                        save_learning_data(learn_data)
            except Exception as e:
                print(f"[{symbol}] AI ERROR: {e}")
                return

        # --- 4. PROCESS DECISION ---
        if decision:
            ai_action = decision.get("action", "HOLD")
            ai_reason = decision.get("reason", "No reasoning")
            ai_sl = decision.get("sl_price")
            ai_tp = decision.get("tp_price")

            # --- INTENT MEMORY SAVING ---
            reason_lower = ai_reason.lower()
            if ai_action == "HOLD":
                if "overextend" in reason_lower or "chasing" in reason_lower or "pullback" in reason_lower:
                    if is_overextended_short:
                        learn_data.setdefault("intent_memory", {})[symbol] = "WAITING FOR PULLBACK TO EMA TO ENTER SHORT"
                    elif is_overextended_long:
                        learn_data.setdefault("intent_memory", {})[symbol] = "WAITING FOR PULLBACK TO EMA TO ENTER LONG"
                # else keep whatever intent was there, or maybe we just don't clear it immediately
            elif ai_action in ["LONG", "SHORT"]:
                # If we entered a trade, clear the intent memory
                if "intent_memory" in learn_data and symbol in learn_data["intent_memory"]:
                    learn_data["intent_memory"][symbol] = ""
            save_learning_data(learn_data)

            if BOT_MEMORY_OK:
                try:
                    bot_memory.save_decision(
                        symbol=symbol, action=ai_action, reasoning=ai_reason,
                        context={"price": current_price, "rsi": rsi, "ema": ema, "market_regime": market_regime, "wave": decision.get("wave_analysis")},
                        nexus_score=nexus_state.get("nexus_score"), confidence=decision.get("scale", 1.0)
                    )
                    bot_memory.update_market_state_cache(
                        symbol=symbol, nexus_score=nexus_state.get("nexus_score", 5.0),
                        macro_bias=nexus_state.get("macro_bias", "NEUTRAL"), last_action=ai_action
                    )
                except Exception as _me:
                    print(f"[MEMORY] Decision save error: {_me}")

            raw_scale = decision.get("scale", 1.0)
            ai_scale = float(raw_scale if raw_scale is not None else 1.0)
            raw_lev = decision.get("leverage", 20)
            suggested_leverage = int(raw_lev if raw_lev is not None else 20)
            ai_leverage = get_dynamic_leverage(symbol, nexus_state.get('nexus_score', 5.0), fgi_score, adx, suggested_leverage)
            
            signal_dir = None
            if ai_action in ["LONG", "SHORT"]:
                # Guard: No dual positions
                if GLOBAL_STATE['open_trades'].get(symbol, {}).get("active", False):
                    return
                # --- CIRCUIT BREAKER CHECK (per-side AND per-symbol) ---
                if CIRCUIT_BREAKER_OK:
                    # Check specific side
                    blocked, cb_reason = circuit_breaker.is_blocked(symbol, ai_action)
                    if blocked:
                        print(f"[{symbol}] 🔴 {cb_reason}", flush=True)
                        send_telegram_message(f"🔴 *[{symbol}] CIRCUIT BREAKER*\n`{cb_reason}`")
                        return
                    # Also check opposite side — if bot keeps flipping LONG↔SHORT on same symbol
                    opposite = "SHORT" if ai_action == "LONG" else "LONG"
                    opp_blocked, opp_reason = circuit_breaker.is_blocked(symbol, opposite)
                    cb_status = circuit_breaker.get_status()
                    long_losses = cb_status.get(f"{symbol}_LONG", {}).get("consecutive_losses", 0)
                    short_losses = cb_status.get(f"{symbol}_SHORT", {}).get("consecutive_losses", 0)
                    total_recent_losses = long_losses + short_losses
                    if total_recent_losses >= 4:
                        print(f"[{symbol}] ⚠️  SYMBOL FATIGUE: {total_recent_losses} combined recent losses (LONG:{long_losses} + SHORT:{short_losses}). Reducing scale.", flush=True)
                        # Force scale down — inject caution (don't block, but warn AI)
                        ai_scale = min(ai_scale, 0.3)
                signal_dir = ai_action
            elif ai_action == "EXIT" and is_revaluation:
                # Early Exit implementation
                trade = GLOBAL_STATE['open_trades'][symbol]
                pnl_pct = ((current_price - trade['entry_price']) / trade['entry_price'] * 100) if trade['side'] == 'BUY' else ((trade['entry_price'] - current_price) / trade['entry_price'] * 100)
                if not is_test_mission and pnl_pct > 0 and pnl_pct < 1.0:
                     print(f"[{symbol}] EXIT BLOCKED: AI attempted to cut winners early ({pnl_pct:.2f}%). Forcing HOLD.", flush=True)
                     return
                trade_age = time.time() - trade.get("entry_time", time.time())
                
                # V24.0 Smart Early Exit bypass
                is_deep_underwater = False
                sl_prc = float(trade.get('current_sl', 0))
                entry_prc = float(trade['entry_price'])
                if sl_prc > 0 and entry_prc > 0:
                    if trade['side'] == 'BUY' and current_price < entry_prc:
                        is_deep_underwater = (entry_prc - current_price) / (entry_prc - sl_prc) > 0.5
                    elif trade['side'] == 'SELL' and current_price > entry_prc:
                        is_deep_underwater = (current_price - entry_prc) / (sl_prc - entry_prc) > 0.5
                
                if not is_test_mission and trade_age < 1800 and not is_deep_underwater:
                    print(f"[{symbol}] EARLY EXIT BLOCKED: Position too young ({trade_age/60:.1f} min) and not deep underwater.", flush=True)
                    return
                print(f"[{symbol}] AI DICTATOR ORDERS EARLY EXIT: {ai_reason}")
                exit_side = 'SELL' if trade['side'] == 'BUY' else 'BUY'
                cancel_all_orders(symbol)
                order_res = place_market_order(symbol, exit_side, trade['qty'], reduce_only=True)
                if order_res and 'orderId' in order_res:
                    trade["active"] = False
                    send_telegram_message(f"🏁 *[{symbol}] EARLY EXIT PROTOCOL*\n\n*Reasoning:* {ai_reason}\n*Exit price:* `{current_price}`")
                    log_trade("EXIT", symbol, trade['qty'], current_price, 0, 0, 0, f"Early Exit: {ai_reason}")
                return
            else:
                if not is_test_mission:
                    print(f"[{symbol}] AI Dictator: {ai_action}. Reason: {ai_reason}", flush=True)

            if signal_dir:
                qty_precision = get_symbol_precision(symbol)
                price_precision = get_price_precision(symbol)
                
                # Default SL/TP for tests if not provided
                if is_test_mission:
                    if not ai_sl: ai_sl = current_price * 0.98 if signal_dir == "LONG" else current_price * 1.02
                    if not ai_tp: ai_tp = current_price * 1.05 if signal_dir == "LONG" else current_price * 0.95
                
                if ai_sl and ai_tp:
                    sl_price = round(float(ai_sl), price_precision)
                    tp_price = round(float(ai_tp), price_precision)
                    risk_dist = abs(current_price - sl_price)

                    if not is_test_mission:
                        # === v23.8 SL/TP ENFORCEMENT (ATR-based floors) ===
                        max_allowed_risk = current_price * 0.10  # Cap: 10% max
                        min_sl_distance = atr * 2.0               # Floor: 2.0x ATR minimum
                        min_rr = 1.5                              # Minimum Risk:Reward ratio

                        # --- SL CAP (Absurdly wide → 10% max) ---
                        if risk_dist > max_allowed_risk:
                            old_sl = sl_price
                            sl_price = round(
                                current_price - max_allowed_risk if signal_dir == "LONG" else current_price + max_allowed_risk,
                                price_precision
                            )
                            risk_dist = abs(current_price - sl_price)
                            print(f"[{symbol}] SL CAP: {old_sl} → {sl_price} (was > 10%)", flush=True)

                        # --- SL FLOOR (Must be at least 1.0x ATR from entry) ---
                        if risk_dist < min_sl_distance:
                            old_sl = sl_price
                            sl_price = round(
                                current_price - min_sl_distance if signal_dir == "LONG" else current_price + min_sl_distance,
                                price_precision
                            )
                            risk_dist = abs(current_price - sl_price)
                            print(
                                f"[{symbol}] SL ATR FLOOR: {old_sl} → {sl_price} "
                                f"(AI placed SL at {abs(current_price - old_sl)/atr:.2f}x ATR, enforced to 2.0x ATR = {min_sl_distance:.4f})",
                                flush=True
                            )

                        # --- TP FLOOR (Must give R:R >= 2.0) ---
                        reward_dist = abs(tp_price - current_price)
                        if risk_dist > 0 and reward_dist < (risk_dist * min_rr):
                            old_tp = tp_price
                            tp_price = round(
                                current_price + (risk_dist * min_rr) if signal_dir == "LONG" else current_price - (risk_dist * min_rr),
                                price_precision
                            )
                            reward_dist = abs(tp_price - current_price)
                            rr_actual = reward_dist / risk_dist
                            print(
                                f"[{symbol}] TP R:R FLOOR: {old_tp} → {tp_price} "
                                f"(Enforced min R:R={min_rr}, actual={rr_actual:.2f})",
                                flush=True
                            )
                        else:
                            rr_actual = reward_dist / risk_dist if risk_dist > 0 else 0

                        # --- LEVERAGE CAP (max x5) ---
                        if ai_leverage > 5:
                            print(f"[{symbol}] LEVERAGE CAP: {ai_leverage}x → 5x", flush=True)
                            ai_leverage = 5

                        print(
                            f"[{symbol}] FINAL SL/TP: SL={risk_dist/current_price*100:.3f}% ({risk_dist/atr:.2f}x ATR), "
                            f"TP={reward_dist/current_price*100:.3f}% ({reward_dist/atr:.2f}x ATR), R:R={rr_actual:.2f}, Lev=x{ai_leverage}",
                            flush=True
                        )

                    if risk_dist > 0:
                        raw_qty = (risk_amount / risk_dist) * ai_scale
                    else:
                        raw_qty = risk_amount / current_price

                    qty = round(raw_qty, qty_precision)
                    print(f"[{symbol}] QTY CALC: raw={raw_qty:.4f}, prec={qty_precision}, final={qty}", flush=True)

                if qty == 0: 
                    print(f"[{symbol}] EXECUTION HALTED: QTY is 0. (Raw: {raw_qty if 'raw_qty' in locals() else 'N/A'})", flush=True)
                    return
                
                # Margin Awareness Check
                max_allowed_notional = wallet_bal * ai_leverage * 0.95 
                notional_value = qty * current_price
                if notional_value > max_allowed_notional:
                    qty = round(max_allowed_notional / current_price, qty_precision)
                if qty == 0: return
                
                print(f"[{symbol}] DEBUG EXECUTION: signal={signal_dir}, qty={qty}, lev={ai_leverage}, sl={sl_price}, tp={tp_price}", flush=True)

                # [v24.2] Global execution gate — serializes order placement across threads.
                # No hard position limit — bot can hold multiple positions if margin allows.
                with ORDER_EXECUTION_LOCK:
                    # Re-check available balance inside the lock (after previous thread may have consumed some)
                    fresh_bal = get_balance()
                    fresh_available = fresh_bal.get('available', 0)
                    required_margin = qty * current_price / ai_leverage * 1.05  # +5% buffer for fees
                    if fresh_available < required_margin:
                        print(f"[{symbol}] ENTRY BLOCKED: Insufficient margin ({fresh_available:.2f} USDT available, need {required_margin:.2f}). Skipping.", flush=True)
                        return

                    set_leverage(symbol, ai_leverage)
                    side = 'BUY' if signal_dir == 'LONG' else 'SELL'
                    
                    # V24.0: Remove hard TP Limit order, prepare for Trailing Stop
                    order_res = place_market_order(symbol, side, qty, sl=sl_price, tp=0)
                    print(f"[{symbol}] ORDER RESPONSE: {order_res}", flush=True)
                
                if order_res and (order_res.get('orderId') or order_res.get('id')):
                    final_order_id = order_res.get('orderId') or order_res.get('id')
                    
                    # V24.0: Set Native Bybit Trailing Stop (Trailing distance = 2.5 ATR)
                    trailing_distance = round(atr * 2.5, price_precision)
                    # Activate it ONLY after hitting the AI's designated Take Profit level
                    active_prc = tp_price
                    bybit.set_trailing_stop(symbol, trailing_dist=trailing_distance, active_price=active_prc)
                    print(f"[{symbol}] V24.0 TRAILING STOP PREPARED: Dist={trailing_distance}, Activates at TP={active_prc}", flush=True)

                    log_trade(signal_dir, symbol, qty, current_price, sl_price, 0, ai_leverage, ai_reason)
                    # [v23.4] fire_bridge is unnecessary for Bybit V5 (native TP/SL)
                    
                    if BOT_MEMORY_OK:
                        try:
                            # === ENRICH CONTEXT: Funding Rate + CVD ===
                            _funding_rate = "N/A"
                            _cvd = "N/A"
                            try:
                                import requests as _req
                                # Funding rate
                                _fr = _req.get(
                                    'https://api.bybit.com/v5/market/funding/history',
                                    params={'category': 'linear', 'symbol': symbol, 'limit': 1},
                                    timeout=3
                                ).json()
                                _fr_data = _fr.get('result', {}).get('list', [{}])
                                if _fr_data:
                                    _funding_rate = float(_fr_data[0].get('fundingRate', 0))
                                # CVD — sum of (buy-vol - sell-vol) on 1m bars for last 5 bars
                                _k = _req.get(
                                    'https://api.bybit.com/v5/market/kline',
                                    params={'category': 'linear', 'symbol': symbol, 'interval': '1', 'limit': 5},
                                    timeout=3
                                ).json()
                                _bars = _k.get('result', {}).get('list', [])
                                _cvd_val = 0.0
                                for _b in _bars:
                                    _o, _c, _vol = float(_b[1]), float(_b[4]), float(_b[5])
                                    # Bullish bar: volume goes to buyers; bearish: to sellers
                                    _cvd_val += _vol if _c >= _o else -_vol
                                _cvd = round(_cvd_val, 2)
                            except Exception:
                                pass

                            _trade_id = bot_memory.save_trade_open(
                                symbol=symbol, side=signal_dir, entry_price=current_price, qty=qty,
                                context={
                                    "sl": sl_price, "tp": tp_price, "leverage": ai_leverage,
                                    "reason": ai_reason,
                                    # Quantitative market state
                                    "rsi": round(rsi, 2),
                                    "atr": round(atr, 4),
                                    "ema": round(ema, 4),
                                    "market_regime": market_regime,
                                    "adx": round(adx, 2),
                                    "sfp": sfp_signal if sfp_signal else "None",
                                    "symmetry": symmetry_desc,
                                    "nexus_score": nexus_state.get("nexus_score", 5.0),
                                    "macro_bias": nexus_state.get("macro_bias", "NEUTRAL"),
                                    "wave_analysis": decision.get("wave_analysis", ""),
                                    "scale": ai_scale,
                                    "portfolio": portfolio_summary,
                                    "planned_rr": round(abs(tp_price - current_price) / abs(sl_price - current_price), 2) if abs(sl_price - current_price) > 0 else 0,
                                    # Bot-requested enrichment (for lesson quality)
                                    "funding_rate": _funding_rate,
                                    "cvd_5m": _cvd,
                                }
                            )
                            GLOBAL_STATE['open_trades'][symbol]["memory_trade_id"] = _trade_id
                            # [v23.4] Crucial for position tracking and auto-close
                            GLOBAL_STATE['open_trades'][symbol].update({
                                "active": True,
                                "side": signal_dir,
                                "qty": qty,
                                "entry_price": current_price,
                                "sl": sl_price,
                                "tp": tp_price
                            })
                        except Exception as e: 
                             print(f"[{symbol}] DB SAVE ERROR: {e}")

                    emoji = "⚡" if is_test_mission else ("🚀" if signal_dir == "LONG" else "🔻")
                    msg = f"{emoji} *[{symbol}] MISSION ACTIVE ({version.VERSION}): {signal_dir}*\n\n*Reasoning:* {ai_reason}\n*Price:* `{current_price}` | *Leverage:* x{ai_leverage}"
                    send_telegram_message(msg)
                else:
                    print(f"[{symbol}] Quant execution error: {order_res}")
                 
    except Exception as e:
        print(f"[{symbol}] Gemini API/Logic error: {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        SYMBOL_LOCKS[symbol].release()
        GLOBAL_STATE['is_evaluating_ai'][symbol] = False

def main():
    global GLOBAL_STATE
    # [v22.8.2] Network stabilization after restart
    time.sleep(3)
    print(f"--------------------------------------------------")
    print(f"--- STARTING ANTIGRAVITY ENGINE {version.VERSION} ({version.CODENAME}) ---")
    print(f"--------------------------------------------------")
    
    # Initial Cache Systems
    load_exchange_info()
    
    # Initial Time Sync (BYBIT NATIVE)
    sync_server_time()
    
    send_telegram_message(f"🚀 *ANTIGRAVITY ENGINE RESTARTED*\nWersja: `{version.FULL_VERSION}`\nTryb: Bybit Live Trading")
    send_telegram_message("🔔 Diagnostics: Engine v22.8.3 successfully started (Migration to Bybit COMPLETE).")
    
    print("Initializing Klines Cache buffer...", flush=True)
    learn_data = load_learning_data()
    for symbol in SYMBOLS:
        params = learn_data.get("parameters", {}).get(symbol, {})
        limit = params.get('ema_period', 50) + 50
        cache = get_klines(symbol, INTERVAL, limit=limit)
        for c in cache:
            c["is_closed"] = True
        GLOBAL_STATE['klines_cache'][symbol] = cache
        
    print("Restoring position state from exchange...", flush=True)
    
    # Step 5: Dirty Order Sweep - cancel stale orders for symbols we won't recover into GLOBAL_STATE
    print("[STARTUP] Dirty Order Sweep: checking hanging orders...", flush=True)
    all_open_orders = binance_request('/fapi/v1/openOrders', '')
    if isinstance(all_open_orders, list) and len(all_open_orders) > 0:
        # Build a set of symbols with open positions
        positions_check = binance_request('/fapi/v2/positionRisk')
        active_symbols_with_pos = set()
        if isinstance(positions_check, list):
            for p in positions_check:
                if float(p.get('positionAmt', 0)) != 0:
                    active_symbols_with_pos.add(p['symbol'])
        
        for order in all_open_orders:
            sym = order.get('symbol', '')
            if sym not in active_symbols_with_pos:
                print(f"[STARTUP] Canceling hanging order {order.get('orderId')} for {sym} (no position)...")
                binance_request('/fapi/v1/order', f"symbol={sym}&orderId={order['orderId']}", method='DELETE', silent=True)
    else:
        print("[STARTUP] Dirty Order Sweep: no hanging orders.", flush=True)

    positions = binance_request('/fapi/v2/positionRisk')
    if isinstance(positions, list):
        for pos in positions:
            symbol = pos['symbol']
            qty = float(pos['positionAmt'])
            if qty != 0:
                entry = float(pos['entryPrice'])
                best_p = float(pos['markPrice'])
                side = 'BUY' if qty > 0 else 'SELL'
                
                # Restoring current SL from exchange
                algo_id = None
                sl_curr = 0
                algo_orders = binance_request('/fapi/v1/openAlgoOrders', f"symbol={symbol}")
                if isinstance(algo_orders, list):
                    stops = [o for o in algo_orders if o.get('orderType') == 'STOP_MARKET']
                    if stops:
                        main_stop = stops[-1]
                        algo_id = main_stop['algoId']
                        sl_curr = float(main_stop['triggerPrice'])
                        for s_to_del in stops[:-1]:
                            binance_request('/fapi/v1/algoOrder', f"symbol={symbol}&algoId={s_to_del['algoId']}", method='DELETE', silent=True)
                                 
                # Restoring TP from exchange (V21.5)
                tp1_recovered = 0
                tp2_recovered = 0
                tp1_hit_recovered = False
                tp2_hit_recovered = False
                
                all_orders = binance_request('/fapi/v1/openOrders', f"symbol={symbol}")
                limit_tps = []
                if isinstance(all_orders, list):
                    tp_side = 'SELL' if side == 'BUY' else 'BUY'
                    limit_tps = [o for o in all_orders if o.get('type') == 'LIMIT' and o.get('side') == tp_side and o.get('reduceOnly')]
                    limit_tps.sort(key=lambda x: float(x['price']), reverse=(side == 'SELL'))
                    
                    # CLEAN UP REDUNDANT ORDERS
                    if len(limit_tps) > 2:
                        print(f"[{symbol}] Detected {len(limit_tps)} TP orders. Cleaning up redundant...")
                        for o in limit_tps[2:]:
                            binance_request('/fapi/v1/order', f"symbol={symbol}&orderId={o['orderId']}", method='DELETE', silent=True)
                        limit_tps = limit_tps[:2]

                    if len(limit_tps) == 2:
                        tp1_recovered = float(limit_tps[0]['price'])
                        tp2_recovered = float(limit_tps[1]['price'])
                    elif len(limit_tps) == 1:
                        tp2_recovered = float(limit_tps[0]['price'])
                        tp1_hit_recovered = True
                        tp1_recovered = round(entry + (tp2_recovered - entry) / 2, get_price_precision(symbol))
                
                if symbol in SYMBOLS:
                    status_extra = f" (TP1 HIT, TP2: {tp2_recovered})" if tp1_hit_recovered else f" (TP1: {tp1_recovered}, TP2: {tp2_recovered})"
                    
                    # Ensure current_sl in memory reflects the ladder level if we recovered a HIT
                    recovered_sl = sl_curr
                    if tp2_hit_recovered and tp1_recovered > 0:
                        recovered_sl = tp1_recovered
                    elif tp1_hit_recovered:
                        recovered_sl = round(entry * (1.001 if side == 'BUY' else 0.999), get_price_precision(symbol))
                    
                    recovered_entry_time = pos.get('updateTime', int(time.time() * 1000)) / 1000.0

                    GLOBAL_STATE['open_trades'][symbol] = {
                        "entry_price": entry,
                        "best_price": best_p,
                        "current_sl": recovered_sl, # Use the recovered ladder level
                        "algo_id": algo_id,
                        "side": side,
                        "qty": abs(qty),
                        "qty_at_start": abs(qty), # Recovery assumes current qty is start if we just loaded
                        "active": True,
                        "entry_time": recovered_entry_time,
                        "tp_1": tp1_recovered,
                        "tp_2": tp2_recovered,
                        "tp_3": None,
                        "tp_4": None,
                        "tp_level": 2 if tp2_hit_recovered else (1 if tp1_hit_recovered else 0),
                        "tp1_hit": tp1_hit_recovered,
                        "tp2_hit": tp2_hit_recovered,
                        "tp_order_ids": [o['orderId'] for o in limit_tps],
                        "is_expanding": False,
                        "force_sl_update": True, # Force sync on startup
                        "last_pos_check": time.time()
                    }
                    print(f"[{symbol}] Restored position {side}{status_extra}. Tracker active (SL: {recovered_sl}).")
                    
    GLOBAL_STATE['last_optimization'] = time.time()
    
    # === OFFLINE SYNC (Offline Orders Sync) ===
    run_periodic_db_sync(tag="STARTUP")
    
    # [v22.8.1] Forced export to Dashboard right after startup
    print("[STARTUP] Exporting initial state to Dashboard...", flush=True)
    export_dashboard_state()

    # Start background thread (only once!)
    t = threading.Thread(target=background_tasks, daemon=True)
    t.start()
    
    # Start Telegram Channel Reader (only once!)
    if TG_READER_AVAILABLE:
        telegram_reader.start_reader_thread()
    
    # 3. Initial Nexus update (Safe execution in background)
    if NEXUS_WORKER_AVAILABLE:
        print(f"[{version.VERSION}] Initializing first Nexus Alpha update...", flush=True)
        threading.Thread(target=ai_nexus_worker.update_nexus, args=("STARTUP_INITIALIZATION",), daemon=True).start()

    # Start Telegram Video Bridge (Daemon mode)
    try:
        if os.path.exists('antigravity_video.session'):
            # [Fix v23.1] Kill existing bridge instances to prevent sqlite3 lock errors
            subprocess.run(["pkill", "-f", "telegram_video_bridge.py"], capture_output=True)
            
            bridge_cmd = [sys.executable, "telegram_video_bridge.py", "--daemon"]
            subprocess.Popen(bridge_cmd, start_new_session=True)
            print(f"[{version.VERSION}] Telegram Video Bridge started in DAEMON mode.", flush=True)
        else:
            print(f"[{version.VERSION}] No session file (.session). Video Bridge cannot start automatically.", flush=True)
    except Exception as e:
        print(f"[{version.VERSION}] Video Bridge start error: {e}", flush=True)
    # BANNER TELEGRAM
    send_telegram_message(f"🚀 *Antigravity Engine Active {version.VERSION} ({version.CODENAME})*\nAction: Project Cleanup & Half-Cooldown Experiment. Status: Full AI Delegation.")
    
    # Reconnect loop (Bybit V5)
    while True:
        try:
            is_testnet = os.getenv('IS_BYBIT_TESTNET', 'False').lower() == 'true'
            pub_url = "wss://stream-testnet.bybit.com/v5/public/linear" if is_testnet else "wss://stream.bybit.com/v5/public/linear"
            priv_url = "wss://stream-testnet.bybit.com/v5/private" if is_testnet else "wss://stream.bybit.com/v5/private"
            sub_msg_pub = json.dumps({"op": "subscribe", "args": [f"kline.1.{s}" for s in SYMBOLS]})

            def start_ping_loop(ws_obj, name):
                def run():
                    while True:
                        if not ws_obj.sock or not ws_obj.sock.connected:
                            break
                        try:
                            ws_obj.send(json.dumps({"op": "ping"}))
                            time.sleep(10)
                        except: break
                threading.Thread(target=run, daemon=True).start()

            def run_public_stream():
                while True:
                    try:
                        def on_open_pub(ws):
                            ws.send(sub_msg_pub)
                            start_ping_loop(ws, "PUBLIC")
                            print("[WSS] Subscribed to Bybit V5 PUBLIC Streams.", flush=True)
                        
                        ws_pub = websocket.WebSocketApp(pub_url,
                                                     on_open=on_open_pub,
                                                     on_message=on_message,
                                                     on_error=on_error,
                                                     on_close=lambda ws, code, msg: print(f"[WSS] PUBLIC Closed: {code} {msg}"))
                        ws_pub.run_forever()
                    except Exception as e:
                        print(f"[WSS RECONNECT] Public Error: {e}")
                    time.sleep(5)

            def run_private_stream():
                api_key = os.getenv('BYBIT_API_KEY')
                api_secret = os.getenv('BYBIT_API_SECRET')
                while True:
                    try:
                        expires = int((time.time() + 60) * 1000)
                        signature = hmac.new(bytes(api_secret, 'utf-8'), 
                                            bytes(f'GET/realtime{expires}', 'utf-8'), hashlib.sha256).hexdigest()
                        auth_msg = json.dumps({"op": "auth", "args": [api_key, expires, signature]})
                        sub_msg_priv = json.dumps({"op": "subscribe", "args": ["position", "execution"]})

                        def on_open_priv(ws):
                            ws.send(auth_msg)
                            ws.send(sub_msg_priv)
                            start_ping_loop(ws, "PRIVATE")
                            print("[WSS] Subscribed to Bybit V5 PRIVATE Streams.", flush=True)

                        ws_priv = websocket.WebSocketApp(priv_url,
                                                      on_open=on_open_priv,
                                                      on_message=on_message,
                                                      on_error=on_error,
                                                      on_close=lambda ws, code, msg: print(f"[WSS] PRIVATE Closed: {code} {msg}"))
                        ws_priv.run_forever()
                    except Exception as e:
                        print(f"[WSS RECONNECT] Private Error: {e}")
                    time.sleep(5)

            # Starting both independently
            threading.Thread(target=run_public_stream, daemon=True).start()
            run_private_stream() # This blocks the main thread
            
        except Exception as e:
            print(f"[MAIN] Critical error in main bot loop: {e}", flush=True)
            time.sleep(5)

if __name__ == '__main__':
    main()
