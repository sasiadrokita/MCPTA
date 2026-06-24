import os
import json
import threading
from datetime import datetime, timezone
import sqlite3

import memory
import ai_gateway

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_NAME = 'gemini-2.5-flash'

def _extractor_worker(trade_id: int):
    """Main analysis logic for a single trade, runs in the background."""
    try:
        # 1. Fetch trade
        trade = memory.get_trade_by_id(trade_id)
        if not trade:
            print(f"[LESSON EXTRACTOR] Trade with ID {trade_id} not found", flush=True)
            return
            
        symbol = trade['symbol']
        side = trade['side']
        entry_price = trade['entry_price']
        exit_price = trade['exit_price']
        pnl = trade.get('pnl', 0.0)
        open_ts = trade['open_ts']
        close_ts = trade.get('close_ts', 'UNKNOWN')
        context = trade.get('context', '{}')
        
        # 2. Construct prompt
        result_txt = "LOSS (ERROR TO FIX)" if pnl < 0 else "PROFIT (SUCCESS TO REPLICATE)"
        
        # Parse context for structured display
        try:
            ctx_data = json.loads(context) if isinstance(context, str) else (context or {})
        except Exception:
            ctx_data = {}
        
        ctx_lines = []
        field_labels = {
            "market_regime": "Market Regime", "adx": "ADX", "rsi": "RSI (15m)", "atr": "ATR",
            "macro_bias": "Nexus Macro Bias", "nexus_score": "Nexus Score",
            "sfp": "SFP Signal", "symmetry": "BTC/ETH Symmetry",
            "wave_analysis": "Elliott Wave Context", "sl": "Stop Loss", "tp": "Take Profit",
            "leverage": "Leverage", "planned_rr": "Planned R:R", "portfolio": "Portfolio State",
            "funding_rate": "Funding Rate (at entry)", "cvd_5m": "CVD 5-min (at entry, +ve=buyers, -ve=sellers)",
            "reason": "AI Entry Reasoning"
        }
        for field, label in field_labels.items():
            if field in ctx_data:
                ctx_lines.append(f"  - {label}: {ctx_data[field]}")
        ctx_summary = "\n".join(ctx_lines) if ctx_lines else str(context)

        prompt = f"""
You are the lead analyst of Antigravity AI. Your task is to extract a CONTEXT-DEPENDENT lesson from this completed trade.

*** TRADE DATA ***
Symbol: {symbol}
Type: {side}
Result: {result_txt} (PnL: {pnl:.2f} USDT)
Entry: {entry_price} ({open_ts})
Exit: {exit_price} ({close_ts})

*** FULL MARKET CONTEXT AT ENTRY ***
{ctx_summary}

*** CRITICAL TASK ***
Analyze WHY this trade succeeded or failed given the SPECIFIC market conditions at entry.

KEY INSIGHT: Overfitted rules with too many conditions NEVER trigger again. 
- Example of WRONG lesson (overfitted): "IF RSI < 30 AND ADX < 20 AND Regime is RANGE_BOUND AND CVD > 1000 THEN..."
- Example of CORRECT lesson (generalized): "IF Regime is RANGE_BOUND AND ADX < 20 THEN AVOID shorting breakouts. The lack of trend guarantees a whip-saw."

Generate one concise, iron-clad CONDITIONAL rule.
LIMIT the IF condition to ONE or maximum TWO variables (e.g., just Regime + one indicator). NEVER chain more than two conditions!

Respond STRICTLY in JSON format (no markdown blocks), using exactly these keys:
{{
    "rule_if": "A concise condition using MAX TWO variables from the context. Be precise about thresholds.",
    "rule_then": "Operational directive: what the bot SHOULD or SHOULD NOT do in that specific constellation.",
    "rule_because": "Short, precise causal explanation based on this specific trade outcome."
}}
"""

        # 3. Call model
        response_text = ai_gateway.generate_content(
            prompt,
            model=MODEL_NAME,
            response_mime='application/json'
        )
        
        if not response_text:
            print("[LESSON EXTRACTOR] No response from AI Gateway.", flush=True)
            return

        # 4. Parse response
        result = json.loads(response_text)
        
        rule_if = result.get('rule_if', 'N/A')
        rule_then = result.get('rule_then', 'N/A')
        rule_because = result.get('rule_because', 'N/A')
        
        # 5. Save lesson
        print(f"\n💡 [LESSON EXTRACTED] for {symbol}: IF {rule_if} THEN {rule_then}", flush=True)
        memory.save_lesson(symbol, rule_if, rule_then, rule_because, trade_id)

    except json.JSONDecodeError as je:
         print(f"[LESSON EXTRACTOR] AI JSON parsing error: {je}", flush=True)
    except Exception as e:
        print(f"[LESSON EXTRACTOR] Critical error: {e}", flush=True)

def trigger_lesson_extraction(trade_id: int):
    """
    Triggers lesson extraction in a separate thread 
    to avoid blocking the main WebSocket loop.
    """
    if trade_id is None or trade_id < 0:
        return
        
    t = threading.Thread(target=_extractor_worker, args=(trade_id,))
    t.start()


def compress_lessons_daily(symbol: str) -> str:
    """
    Called once a day (e.g., from an audit or maintenance script).
    Compresses all accumulated JSON lessons into a succinct 'Golden Rules' list.
    """
    try:
        learn_path = os.path.join(BASE_DIR, 'autonomic_learning.json')
        if not os.path.exists(learn_path):
            return f"[{symbol}] No learning file found."
            
        with open(learn_path, 'r', encoding='utf-8') as f:
            learn_data = json.load(f)
            
        key = f'ai_lessons_learned_{symbol}'
        raw_lessons = learn_data.get(key, "")
        
        # Count lines roughly to see if compression is needed
        lines_count = len(raw_lessons.split('\n'))
        if lines_count < 20:
            return f"[{symbol}] Only {lines_count} lessons. Compression not needed yet."

        # Fetch recent performance to inform RL
        conn = sqlite3.connect(memory.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT side, pnl, context, close_reason FROM trades WHERE symbol = ? ORDER BY id DESC LIMIT 20", (symbol,))
        recent_trades = cur.fetchall()
        conn.close()

        wins = sum(1 for t in recent_trades if t[1] > 0)
        losses = sum(1 for t in recent_trades if t[1] <= 0)
        win_rate = round(wins / (wins + losses) * 100, 1) if recent_trades else 0
        
        perf_summary = f"Recent {symbol} Performance: {wins} Wins, {losses} Losses (Win Rate: {win_rate}%)\n"
        
        prompt = f"""
You are the Reinforcement Learning Architect for Antigravity AI. 
Your task is to review the accumulated raw trading lessons for {symbol} and compress them into a set of highly effective, non-contradictory "Golden Rules".

*** RECENT PERFORMANCE ***
{perf_summary}

*** RAW LESSONS LOG ***
{raw_lessons}

*** TASK (REINFORCEMENT LEARNING) ***
1. Identify the core patterns that actually lead to success (profits) or prevent failure (losses).
2. Filter out contradictory rules, obsolete strategies, or noise.
3. Consolidate repetitive lessons into single, powerful directives.
4. Format the output as a list of MAX 20 "Golden Rules" (Bullet points).
5. The final output must be extremely concise and direct (max 100 lines total).
6. DO NOT use markdown code blocks like ```json or ```text. Just return the plain text list of rules.

Example Format:
- IF (Trend is DOWN AND Nexus Bias is BEARISH AND RSI < 40) THEN (Prioritize SHORT) BECAUSE (High probability of continuation).
- STRICTLY AVOID longs during extreme volatility (ATR > X).
"""

        compressed_text = ai_gateway.generate_content(
            prompt,
            model=MODEL_NAME
        )
        if not compressed_text:
            return f"[{symbol}] Compression failed via AI Gateway."
            
        compressed_text = compressed_text.strip().replace("```text", "").replace("```", "").strip()
        new_lines_count = len(compressed_text.split('\n'))
        
        # Overwrite with compressed lessons
        learn_data[key] = compressed_text
        with open(learn_path, 'w', encoding='utf-8') as f:
            json.dump(learn_data, f, indent=4)
            
        summary_msg = f"[{symbol}] Compressed {lines_count} lines of lessons into {new_lines_count} Golden Rules."
        print(f"[LESSON COMPRESSION] {summary_msg}", flush=True)
        return summary_msg

    except Exception as e:
        err_msg = f"[{symbol}] Compression error: {e}"
        print(f"[LESSON COMPRESSION] {err_msg}", flush=True)
        return err_msg
