import warnings; warnings.filterwarnings("ignore", category=FutureWarning)
import os
import json
import threading
import google.generativeai as genai
from datetime import datetime, timezone
import memory

# Configuration
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
else:
    print("[LESSON EXTRACTOR] GEMINI API KEY MISSING. Module will not function.", flush=True)

MODEL_NAME = 'gemini-2.5-flash'

def _extractor_worker(trade_id: int):
    """Main analysis logic for a single trade, runs in the background."""
    if not api_key:
        return
        
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
        except:
            ctx_data = {}
        
        ctx_lines = []
        field_labels = {
            "market_regime": "Market Regime", "adx": "ADX", "rsi": "RSI (15m)", "atr": "ATR",
            "macro_bias": "Nexus Macro Bias", "nexus_score": "Nexus Score",
            "sfp": "SFP Signal", "symmetry": "BTC/ETH Symmetry",
            "wave_analysis": "Elliott Wave Context", "sl": "Stop Loss", "tp": "Take Profit",
            "leverage": "Leverage", "planned_rr": "Planned R:R", "portfolio": "Portfolio State",
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

KEY INSIGHT: A rule that applies in one market constellation may NOT apply in another.
- Example of WRONG lesson: "Never open SHORT when RSI is oversold."
- Example of CORRECT lesson: "Never open SHORT when RSI is oversold (<30) AND Nexus Score > 6.0 (BULLISH) AND ADX < 20 (weak trend). In that specific combination, the bounce risk is too high."

Generate one concise, iron-clad CONDITIONAL rule that captures the relationship between market conditions and outcome.

Respond STRICTLY in JSON format (no markdown blocks), using exactly these keys:
{{
    "rule_if": "A very specific combination of market conditions from the entry context (regime, RSI, ADX, nexus bias, SFP, wave, portfolio state) that characterizes THIS specific setup. Be precise about thresholds.",
    "rule_then": "Operational directive: what the bot SHOULD or SHOULD NOT do in that specific constellation. E.g., 'AVOID opening SHORT', or 'PRIORITIZE LONG with scale >= 0.7'.",
    "rule_because": "Short, precise causal explanation based on this specific trade outcome. Explain the market mechanism that caused the profit or loss."
}}
"""

        # 3. Call model
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.2, # Low temp for logical consistency
                response_mime_type="application/json"
            )
        )
        
        # 4. Parse response
        raw_text = response.text.strip()
        result = json.loads(raw_text)
        
        rule_if = result.get('rule_if', 'N/A')
        rule_then = result.get('rule_then', 'N/A')
        rule_because = result.get('rule_because', 'N/A')
        
        # 5. Save lesson
        print(f"\n💡 [LESSON EXTRACTED] for {symbol}: IF {rule_if} THEN {rule_then}", flush=True)
        memory.save_lesson(symbol, rule_if, rule_then, rule_because, trade_id)

    except json.JSONDecodeError as je:
         print(f"[LESSON EXTRACTOR] AI JSON parsing error: {je}\nResponse: {response.text}", flush=True)
    except Exception as e:
        print(f"[LESSON EXTRACTOR] Critical error: {e}", flush=True)

def trigger_lesson_extraction(trade_id: int):
    """
    Triggers lesson extraction in a separate thread 
    to avoid blocking the main WebSocket loop.
    """
    if trade_id is None or trade_id < 0:
        return
        
    thread = threading.Thread(target=_extractor_worker, args=(trade_id,))
    thread.daemon = True # Does not block bot shutdown
    thread.start()
    print(f"[LESSON EXTRACTOR] Learning thread started for Trade ID: {trade_id}", flush=True)
