#!/usr/bin/env python3
"""
Antigravity Dashboard (Managed via version.py)
Local web dashboard for real-time bot monitoring.
Run: python dashboard.py
Open: http://localhost:5000
"""

import os
import json
import subprocess
import sys
import re
import version
import time
from flask import Flask, render_template, jsonify, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(BASE_DIR, 'venv', 'bin', 'python')

app = Flask(__name__, template_folder='templates')

# ─── Helpers ──────────────────────────────────────────────────────────────────

def is_bot_running():
    try:
        result = subprocess.run(['pgrep', '-f', 'autonomic_engine.py'],
                                capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
        return False

def load_nexus():
    path = os.path.join(BASE_DIR, 'nexus_state.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

# ─── Bybit Gateway Integration (Bybit V5) ───────────────────────────────────
from bybit_gateway import BybitGateway
bybit = BybitGateway()

def get_balance():
    """Fetches account balance from Bybit V5 via Gateway (USDT+USDC)."""
    try:
        # Use the improved Gateway method that sums USDT and USDC
        bal = bybit.get_balance()
        
        # Calculate unrealized PnL from positions here for the dashboard
        try:
            positions = bybit.exchange.fetch_positions(params={'category': 'linear'})
            upnl = sum(float(p.get('unrealizedPnl', 0) or 0) for p in positions)
        except Exception:
            upnl = 0.0
            
        return {
            'wallet': bal.get('wallet', 0.0),
            'available': bal.get('available', 0.0),
            'unrealized_pnl': upnl,
            'usdc': bal.get('USDC', 0.0) # Optional view
        }
    except Exception as e:
        print(f"[DASH] get_balance error: {e}")
        return {'available': 0.0, 'wallet': 0.0, 'unrealized_pnl': 0.0}

def get_positions():
    """v23.4: Fetches active positions using the improved Gateway."""
    try:
        # Use the gateway method which already has category='linear'
        return bybit.get_positions()
    except Exception as e:
        print(f"[DASH] get_positions error: {e}")
        return []

def get_raw_intel():
    """Fetches raw analytical data from JSON files for the Transparency view."""
    intel_data = {
        'video': None,
        'email': None,
        'telegram': None,
        'rss': None,
        'ta': None,
        'nexus_score': None
    }

    # 1. Telegram Video Analysis
    video_path = os.path.join(BASE_DIR, 'video_intel_dash.json')
    if os.path.exists(video_path):
        try:
            with open(video_path, 'r', encoding='utf-8') as f:
                intel_data['video'] = json.load(f)
        except Exception: pass

    # 2. Macro Analysis Reports (Email)
    macro_path = os.path.join(BASE_DIR, 'macro_intel.json')
    if os.path.exists(macro_path):
        try:
            with open(macro_path, 'r', encoding='utf-8') as f:
                intel_data['email'] = json.load(f)
        except Exception: pass

    # 3. Telegram Text Signals (from scraper)
    tg_path = os.path.join(BASE_DIR, 'tg_signals.json')
    if os.path.exists(tg_path):
        try:
            with open(tg_path, 'r', encoding='utf-8') as f:
                intel_data['telegram'] = json.load(f)
        except Exception: pass

    # 4. RSS Feed Intel
    rss_path = os.path.join(BASE_DIR, 'rss_intel.json')
    if os.path.exists(rss_path):
        try:
            with open(rss_path, 'r', encoding='utf-8') as f:
                intel_data['rss'] = json.load(f)
        except Exception: pass

    # 5. Technical Analysis (Binance source)
    ta_path = os.path.join(BASE_DIR, 'ta_intel.json')
    if os.path.exists(ta_path):
        try:
            with open(ta_path, 'r', encoding='utf-8') as f:
                intel_data['ta'] = json.load(f)
        except Exception: pass

    # 6. Fusion Result (Nexus Score)
    fusion_path = os.path.join(BASE_DIR, 'fusion_intel.json')
    if os.path.exists(fusion_path):
        try:
            with open(fusion_path, 'r', encoding='utf-8') as f:
                intel_data['nexus_score'] = json.load(f)
        except Exception: pass

    return intel_data

# === HELPER FUNCTIONS FOR INDICATORS ===
def calculate_rsi_array(prices, period=14):
    if len(prices) < period + 1:
        return [None] * len(prices)
    
    rsi_list = [None] * period
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

def calculate_adx_array(klines, period=14):
    if len(klines) < period * 2:
        return [None] * len(klines)
        
    trs = []
    pos_dms = []
    neg_dms = []
    
    for i in range(1, len(klines)):
        high = float(klines[i][2])
        low = float(klines[i][3])
        prev_high = float(klines[i-1][2])
        prev_low = float(klines[i-1][3])
        prev_close = float(klines[i-1][4])
        
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
        return [None] * len(klines)
        
    adx_list = [None] * (period * 2 - 1)
    adx = sum(dx_vals[:period]) / period if len(dx_vals) >= period else sum(dx_vals) / len(dx_vals)
    adx_list.append(adx)
    for i in range(period, len(dx_vals)):
        adx = ((adx * (period - 1)) + dx_vals[i]) / period
        adx_list.append(adx)
        
    # Align to klines length
    diff = len(klines) - len(adx_list)
    if diff > 0:
        adx_list = [None]*diff + adx_list
    elif diff < 0:
        adx_list = adx_list[-len(klines):]
    return adx_list

def get_recent_trades(n=15):
    """v23.8: Fetches recent closed trades from Bybit V5 with full date+time."""
    try:
        res = bybit.exchange.private_get_v5_position_closed_pnl({'category': 'linear', 'limit': n})
        if res.get('retCode') == '0':
            trades_list = res.get('result', {}).get('list', [])
            trades = []
            for t in trades_list:
                ts = int(t.get('updatedTime', 0)) / 1000
                date_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))
                
                # Bybit 'side' in closed_pnl is the CLOSING side.
                # If closing side is Buy, position was SHORT. If Sell, position was LONG.
                closing_side = t.get('side', '').capitalize()
                position_side = 'LONG' if closing_side == 'Sell' else 'SHORT'
                
                trades.append({
                    'time': date_str,
                    'symbol': t.get('symbol', ''),
                    'pnl': float(t.get('closedPnl', 0)),
                    'side': position_side,
                    'entry': t.get('avgEntryPrice', ''),
                    'exit': t.get('avgExitPrice', ''),
                    'leverage': t.get('leverage', ''),
                    'qty': t.get('qty', '')
                })
            return trades
        return []
    except Exception as e:
        print(f"[DASH] get_recent_trades error (Exchange): {e}")
        return []

def get_pnl_summary():
    """Calculates realized Daily and Monthly PnL from Bybit closed positions."""
    try:
        import datetime
        now = datetime.datetime.utcnow()
        # Fetch last 200 closed trades for monthly coverage
        res = bybit.exchange.private_get_v5_position_closed_pnl({'category': 'linear', 'limit': 200})
        if res.get('retCode') != '0':
            return {'daily': 0.0, 'monthly': 0.0}

        trades_list = res.get('result', {}).get('list', [])
        daily_pnl = 0.0
        monthly_pnl = 0.0

        today = now.date()
        this_month = (now.year, now.month)

        for t in trades_list:
            ts = int(t.get('updatedTime', 0)) / 1000
            trade_dt = datetime.datetime.utcfromtimestamp(ts)
            pnl = float(t.get('closedPnl', 0))

            if trade_dt.date() == today:
                daily_pnl += pnl
            if (trade_dt.year, trade_dt.month) == this_month:
                monthly_pnl += pnl

        return {
            'daily': round(daily_pnl, 4),
            'monthly': round(monthly_pnl, 4)
        }
    except Exception as e:
        print(f"[DASH] get_pnl_summary error: {e}")
        return {'daily': 0.0, 'monthly': 0.0}

def get_log_lines(n=30):
    """Reads the last n lines from engine.log."""
    log_path = os.path.join(BASE_DIR, 'engine.log')
    try:
        if not os.path.exists(log_path):
            return ['engine.log does not exist.']
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines[-n:]]
    except Exception as e:
        return [f'Log read error: {e}']

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/status')
def api_status():
    positions = get_positions()
    nexus = load_nexus()
    trades = get_recent_trades()
    logs = get_log_lines()
    balance = get_balance()
    raw_intel = get_raw_intel()
    pnl_summary = get_pnl_summary()

    # Compute total unrealized PnL
    total_pnl = sum(float(p.get('unrealized_pnl', 0)) for p in positions)

    return jsonify({
        'engine_running': is_bot_running(),
        'nexus': nexus,
        'positions': positions,
        'balance': balance,
        'total_pnl': round(total_pnl, 4),
        'recent_trades': trades,
        'log_lines': logs,
        'raw_intel': raw_intel,
        'pnl_summary': pnl_summary,
        'version_info': {
            'version': version.VERSION,
            'codename': version.CODENAME,
            'full': version.FULL_VERSION
        }
    })

@app.route('/api/bot-action', methods=['POST'])
def api_bot_action():
    data = request.get_json(silent=True) or {}
    action = data.get('action', '')

    if action == 'start':
        if is_bot_running():
            return jsonify({'status': 'already_running'})
        start_sh = os.path.join(BASE_DIR, 'start_bot.sh')
        subprocess.Popen(['bash', start_sh], cwd=BASE_DIR,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({'status': 'starting'})

    elif action == 'stop':
        subprocess.run(['pkill', '-f', 'autonomic_engine.py']),
        subprocess.run(['pkill', '-f', 'telegram_video_bridge.py'])
        return jsonify({'status': 'stopped'})

    return jsonify({'status': 'unknown_action'}), 400


# ─── Entrypoint ───────────────────────────────────────────────────────────────

# --- CHARTING MODULE (V24.0) ---
def calculate_ema_local(prices, period):
    if len(prices) < period:
        return [0] * len(prices)
    ema = [sum(prices[:period]) / period]
    multiplier = 2 / (period + 1)
    for price in prices[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    # Pad the beginning with None to match length
    return [None]*(period-1) + ema

@app.route('/api/chart_data')
def api_chart_data():
    symbol = request.args.get('symbol', 'BTCUSDT')
    timeframe = request.args.get('timeframe', '15m')
    # Convert generic symbol to CCXT Bybit Linear format
    base_sym = symbol.replace('/', '').replace(':USDT', '').replace('USDT', '')
    ccxt_symbol = f"{base_sym}/USDT:USDT"
    
    try:
        # Fetch klines
        klines = bybit.exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=500)
        
        # 3. Calculate indicators
        closes = [float(k[4]) for k in klines]
        ema_array = calculate_ema_local(closes, 50)
        rsi_array = calculate_rsi_array(closes, period=14)
        adx_array = calculate_adx_array(klines, period=14)
        
        # 4. Format for Lightweight Charts
        chart_data = []
        for i, k in enumerate(klines):
            ts = int(k[0] / 1000)
            ema_val = ema_array[i]
            rsi_val = rsi_array[i]
            adx_val = adx_array[i]
            
            data_point = {
                'time': ts,
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4])
            }
            if ema_val is not None:
                data_point['ema50'] = round(ema_val, 2)
            if rsi_val is not None:
                data_point['rsi'] = round(rsi_val, 2)
            if adx_val is not None:
                data_point['adx'] = round(adx_val, 2)
                
            chart_data.append(data_point)

        return jsonify({'status': 'ok', 'data': chart_data})
    except Exception as e:
        print(f"[DASH] Chart Data Error: {e}")
        return jsonify({'candles': [], 'ema_50': [], 'error': str(e)})

@app.route('/api/chart_markers')
def api_chart_markers():
    symbol = request.args.get('symbol', 'BTCUSDT')
    markers = []
    
    try:
        # 1. Historical Executions (Entries and Exits)
        base_sym = symbol.replace('/', '').replace(':USDT', '').replace('USDT', '')
        ccxt_symbol = f"{base_sym}/USDT:USDT"
        
        try:
            my_trades = bybit.exchange.fetch_my_trades(symbol=ccxt_symbol, limit=100)
            for t in my_trades:
                ts = int(t['timestamp'] / 1000)
                side = t['side'].upper() # 'BUY' or 'SELL'
                raw = t.get('info', {})
                closed_size = float(raw.get('closedSize', 0) or 0)
                price = float(t['price'])
                
                # Determine if it was an Entry or Exit
                if closed_size > 0:
                    # It's an exit. If we bought to close, we were SHORT. If we sold to close, we were LONG.
                    pos_side = "SHORT" if side == "BUY" else "LONG"
                    markers.append({
                        'time': ts,
                        'position': 'aboveBar',
                        'color': '#8b5cf6', # purple for exits
                        'shape': 'circle',
                        'text': f"Exit {pos_side} ({price})"
                    })
                else:
                    # It's an entry. Buy means LONG, Sell means SHORT.
                    pos_side = "LONG" if side == "BUY" else "SHORT"
                    markers.append({
                        'time': ts,
                        'position': 'belowBar' if pos_side == 'LONG' else 'aboveBar',
                        'color': '#10b981' if pos_side == 'LONG' else '#ef4444',
                        'shape': 'arrowUp' if pos_side == 'LONG' else 'arrowDown'
                    })
        except Exception as e:
            print(f"[DASH] fetch_my_trades error: {e}")

        # 2. Active Positions (Current)
        positions = get_positions()
        for p in positions:
            if p['symbol_raw'] == symbol or p['symbol'] == symbol or p['symbol'].startswith(symbol.replace('USDT','')):
                # CCXT unified or Bybit raw returns createdTime in ms or entry time
                # However `get_positions()` mapped `entry_time` if available, wait, `get_positions` uses `created_time_ms`
                # Let's just put it at the end (current time) if we don't have exact timestamp, or fetch from dict
                ts = int(p.get('entry_time', 0))
                if ts == 0:
                    ts = int(time.time())
                side_str = p['side'].upper()
                markers.append({
                    'time': ts,
                    'position': 'belowBar' if side_str == 'LONG' else 'aboveBar',
                    'color': '#10b981' if side_str == 'LONG' else '#ef4444',
                    'shape': 'arrowUp' if side_str == 'LONG' else 'arrowDown'
                })
                
        # Sort markers by time
        markers.sort(key=lambda x: x['time'])
        return jsonify(markers)
    except Exception as e:
        print(f"[DASH] Marker Error: {e}")
        return jsonify([])

if __name__ == '__main__':
    port = int(os.environ.get('DASHBOARD_PORT', 5000))
    print(f"\n{'─'*55}")
    print(f"  🛸 Antigravity Dashboard {version.VERSION}")
    print(f"  URL: http://localhost:{port}")
    print(f"  Stop: Ctrl+C")
    print(f"{'─'*55}\n")
    app.run(host='0.0.0.0', port=port, debug=False)
