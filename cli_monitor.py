import time
import json
import os
import subprocess
from datetime import datetime
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.console import Console
from rich.text import Text

console = Console()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(BASE_DIR, 'venv', 'bin', 'python')

# --- DATA FETCHING ---

def get_binance_data(command):
    script = f"""
import sys, os, json
sys.path.insert(0, '{BASE_DIR}')
old_stdout = sys.stdout
sys.stdout = open(os.devnull, 'w')
from autonomic_engine import binance_request
sys.stdout = old_stdout

if '{command}' == 'balance':
    data = binance_request('/fapi/v2/balance', '')
    res = {{'available': 0.0, 'wallet': 0.0}}
    if isinstance(data, list):
        for a in data:
            if a.get('asset') == 'USDT':
                res['wallet'] = float(a.get('balance', 0))
                res['available'] = float(a.get('availableBalance', 0))
                break
    print(json.dumps(res))
elif '{command}' == 'positions':
    data = binance_request('/fapi/v2/positionRisk', '')
    active = [p for p in data if float(p.get('positionAmt', 0)) != 0] if isinstance(data, list) else []
    print(json.dumps(active))
elif '{command}' == 'history':
    data = binance_request('/fapi/v1/userTrades', 'limit=10')
    print(json.dumps(data if isinstance(data, list) else []))
"""
    try:
        result = subprocess.run([VENV_PYTHON, '-c', script], capture_output=True, text=True, timeout=10)
        return json.loads(result.stdout.strip().split('\n')[-1])
    except: return None

def get_last_logs(count=12):
    # Look for logs in common places
    for log_name in ['engine.log']:
        path = os.path.join(BASE_DIR, log_name)
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    lines = [l.strip() for l in f.readlines() if l.strip()]
                    return lines[-count:]
            except: pass
    return ["No active logs in engine.log..."]

def load_nexus():
    try:
        with open('nexus_state.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return {}

# --- LAYOUT DEFINITION ---

def make_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="upper", ratio=1),
        Layout(name="nexus_area", ratio=2), # Ample space for intelligence
        Layout(name="footer", size=3)
    )
    layout["upper"].split_row(
        Layout(name="positions", ratio=1),
        Layout(name="history", ratio=1)
    )
    layout["nexus_area"].split_row(
        Layout(name="nexus_text", ratio=2), # Gmail/Video texts
        Layout(name="logs", ratio=1)        # Side logs
    )
    return layout

def generate_dashboard():
    nx = load_nexus()
    bal = get_binance_data('balance') or {'available': 0, 'wallet': 0}
    pos = get_binance_data('positions') or []
    hist = get_binance_data('history') or []
    logs = get_last_logs(12)

    # 1. HEADER
    header = Panel(Text(f"🛸 ANTIGRAVITY MISSION CONTROL | {datetime.now().strftime('%H:%M:%S')}", justify="center", style="bold cyan"), border_style="bright_blue")

    # 2. POSITIONS (Filter 0.00 PnL)
    pos_table = Table(expand=True, title="[bold yellow]Active Positions[/bold yellow]", box=None)
    pos_table.add_column("Symbol")
    pos_table.add_column("Side", justify="center")
    pos_table.add_column("PnL", justify="right")
    
    total_pnl = 0
    for p in pos:
        unpnl = float(p.get('unRealizedProfit', 0))
        if abs(unpnl) < 0.01: continue # SKIP ZEROS
        total_pnl += unpnl
        side = "LONG" if float(p['positionAmt']) > 0 else "SHORT"
        style = "bold green" if side == "LONG" else "bold red"
        pos_table.add_row(p['symbol'], Text(side, style=style), f"{unpnl:+.2f}")

    # 3. HISTORY (Filter 0.00 Profit)
    hist_table = Table(expand=True, title="[bold blue]Recent PnL[/bold blue]", box=None)
    hist_table.add_column("Symbol")
    hist_table.add_column("Profit", justify="right")
    
    shown_hist = 0
    for h in hist:
        real_pnl = float(h.get('realizedPnl', 0))
        if abs(real_pnl) < 0.01: continue # SKIP ZEROS
        color = "green" if real_pnl > 0 else "red"
        hist_table.add_row(h['symbol'], Text(f"{real_pnl:+.2f}", style=color))
        shown_hist += 1
        if shown_hist >= 6: break # Max 6 lines

    # 4. NEXUS INTELLIGENCE (FULL TEXT)
    intel = Text()
    score = nx.get('nexus_score', 0)
    bias = nx.get('macro_bias', 'N/A')
    intel.append(f"SCORE: {score} | BIAS: {bias}\n", style="bold yellow")
    intel.append(f"INSIGHT: {nx.get('ai_comment', '')}\n", style="italic white")
    intel.append("-" * 50 + "\n", style="dim")
    intel.append("🌍 GMAIL: ", style="bold blue")
    intel.append(nx.get('gmail_intel', 'None...') + "\n\n", style="white")
    intel.append("🎥 VIDEO: ", style="bold purple")
    intel.append(nx.get('video_intel', 'None...'), style="white")

    # 5. LOGS
    log_content = Text()
    for l in logs:
        l_style = "green" if "Success" in l or "SUCCESS" in l else "red" if "Error" in l or "ERROR" in l else "dim"
        log_content.append(l[:60] + "\n", style=l_style)

    # 6. FOOTER
    pnl_style = "bold green" if total_pnl >= 0 else "bold red"
    footer_text = Text.assemble(
        (" WALLET: ", "bold white"), (f"{bal['wallet']:.2f} USDT", "bold yellow"),
        (" | PnL: ", "bold white"), (f"{total_pnl:+.2f} USDT", pnl_style),
        (" | Available: ", "bold white"), (f"{bal['available']:.2f} USDT", "dim")
    )

    layout = make_layout()
    layout["header"].update(header)
    layout["positions"].update(Panel(pos_table, border_style="yellow"))
    layout["history"].update(Panel(hist_table, border_style="blue"))
    layout["nexus_text"].update(Panel(intel, title="Nexus Intelligence Core", border_style="magenta", padding=(1,1)))
    layout["logs"].update(Panel(log_content, title="Engine Logs", border_style="white"))
    layout["footer"].update(Panel(footer_text, border_style="bright_blue"))
    
    return layout

if __name__ == "__main__":
    with Live(generate_dashboard(), refresh_per_second=0.5, screen=True) as live:
        try:
            while True:
                time.sleep(5)
                live.update(generate_dashboard())
        except KeyboardInterrupt: pass
