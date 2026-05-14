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
        
        prompt = f"""
You are the lead analyst of Antigravity AI. Your task is to extract a critical, single lesson from the recently completed trade.

*** TRADE DATA ***
Symbol: {symbol}
Type: {side}
Result: {result_txt} (PnL: {pnl:.2f} USDT)
Entry: {entry_price} ({open_ts})
Exit: {exit_price} ({close_ts})
Market Context (T0 - entry moment):
{context}

*** TASK ***
Identify the single most important factor that determined the outcome. 
Generate one, concise, iron-clad rule (Rule) that will protect the system from repeating this error (or help repeat the success).

Respond STRICTLY in JSON format, without markdown blocks (` ```json `), using exactly these keys:
{{
    "rule_if": "A very specific technical/macro condition from the context of this trade, e.g., When RSI is > 80 and Sentiment is BEARISH...",
    "rule_then": "Operational rule for the engine, e.g., DO NOT OPEN LONG positions regardless of correlations...",
    "rule_because": "Short justification derived from the error/success in this specific trade, e.g., In this case, it led to an immediate reversal after hitting a resistance wall."
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
