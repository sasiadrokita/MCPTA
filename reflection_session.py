import os
import json
import time
import re
from ai_gateway import generate_content as ai_generate
from autonomic_engine import binance_request, get_balance, get_fear_greed_index, load_nexus_state, load_learning_data, save_learning_data, get_recent_exchange_trades, SYMBOLS, send_telegram_message
import version

def force_self_reflection():
    print("Initiating AI Autonomous Reflection Session (Post-Mortem)...")
    
    balance = get_balance()
    fgi = get_fear_greed_index()
    nexus = load_nexus_state()
    learn_data = load_learning_data()
    
    lessons = ""
    for k, v in learn_data.items():
        if k.startswith("ai_lessons_learned"):
            symbol = k.replace("ai_lessons_learned_", "")
            lessons += f"- **{symbol}**: {v}\n"

    recent_logs = "No logs."
    if os.path.exists('engine_trades.log'):
        with open('engine_trades.log', 'r') as f:
            lines = f.readlines()
            recent_logs = "".join(lines[-20:])

    exchange_history = get_recent_exchange_trades(limit=25)

    user_feedback = """
    CRITICAL NOTES:
    1. Stop writing in all caps and repeating the same rules over and over. Be concise.
    2. Too many Early Exits without hitting TP.
    3. Ignoring Macro: Nexus Score is Bearish, but you are opening LONGs based only on technicals.
    """

    prompt = f"""
You are the elite Antigravity AI system ({version.VERSION}). You are conducting a "Self-Correction" phase on the Bybit exchange.

--- DATA ---
BALANCE: {balance} USDT
EXCHANGE: {exchange_history}
SENTIMENT: {nexus.get('macro_bias', 'NEUTRAL')} (Score: {nexus.get('nexus_score', 5.0)})
F&G: {fgi}/100
OLD KNOWLEDGE: {lessons}
LOGS: {recent_logs}
{user_feedback}

--- TASK ---
Update AI Lessons (Mental Notes) and generate a comprehensive Polish Telegram report.

CRITICAL Requirement 1 (LESSONS): Compress the knowledge! A new lesson for a given symbol MUST HAVE A MAXIMUM OF 3 SHORT SENTENCES (bulleted) IN ENGLISH. Focus only on pure tactics. Remove old noise.
CRITICAL Requirement 2 (TELEGRAM REPORT): Generate a highly detailed, beautifully formatted Polish Markdown report, matching the classic "Antigravity AI - Raport On-chain & Market Insights" format.

--- STRUCTURE ---
You MUST output EXACTLY two sections wrapped in specific tags.

[REPORT START]
🚀 Antigravity AI {version.FULL_VERSION} - Raport On-chain & Market Insights 🚀
📅 Raport z dnia: [Dzisiejsza data]
... (reszta raportu w polskim Markdown) ...
[REPORT END]

[JSON START]
{{
  "BTCUSDT": "- Point 1.\\n- Point 2.\\n- Point 3.",
  "ETHUSDT": "- Point 1.\\n- Point 2.\\n- Point 3."
}}
[JSON END]
"""
    print("Sending request to AI Gateway...", flush=True)
    response_text = ai_generate(prompt, model='gemini-2.5-flash', response_mime='text/plain', cache_key='reflection_session_v4', timeout=60)
    
    if not response_text:
        print("Error: AI Gateway returned no response.")
        return

    # Extract Report
    report_match = re.search(r'\[REPORT START\](.*?)\[REPORT END\]', response_text, re.DOTALL)
    report_msg = report_match.group(1).strip() if report_match else "Reflection completed (Parsing error in report)."

    # Extract JSON
    json_match = re.search(r'\[JSON START\](.*?)\[JSON END\]', response_text, re.DOTALL)
    new_lessons = {}
    if json_match:
        try:
            new_lessons = json.loads(json_match.group(1), strict=False)
        except Exception as e:
            print(f"Error parsing JSON lessons: {e}")

    try:
        if new_lessons:
            for symbol, consolidated_lesson in new_lessons.items():
                if consolidated_lesson and len(consolidated_lesson) > 5:
                    key = f"ai_lessons_learned_{symbol}"
                    learn_data[key] = consolidated_lesson
            
            save_learning_data(learn_data)
            print(f"[REFL] Updated and compressed autonomic_learning.json.")

        send_telegram_message(f"🧠 *AI SELF-REFLECTION SESSION*\n\n{report_msg}", force=True)
        
        from autonomic_engine import archive_to_black_box
        archive_to_black_box("POST-MORTEM REFLECTION SESSION", report_msg)
        
    except Exception as e:
        print(f"Error processing AI response: {e}")

if __name__ == "__main__":
    force_self_reflection()
