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

if __name__ == '__main__':
    port = int(os.environ.get('DASHBOARD_PORT', 5000))
    print(f"\n{'─'*55}")
    print(f"  🛸 Antigravity Dashboard {version.VERSION}")
    print(f"  URL: http://localhost:{port}")
    print(f"  Stop: Ctrl+C")
    print(f"{'─'*55}\n")
    app.run(host='0.0.0.0', port=port, debug=False)
