import time
import json
import os
import urllib.request as request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import ai_gateway

# Local imports
try: import telegram_reader
except: telegram_reader = None
try: import gmail_intel_bridge
except: gmail_intel_bridge = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, 'nexus_state.json')
MACRO_FILE = os.path.join(BASE_DIR, 'macro_intel.json')
VIDEO_INTEL_FILE = os.path.join(BASE_DIR, 'video_intel.json')

def fetch_crypto_news():
    """Fetches news from a free public RSS feed"""
    try:
        url = "https://www.coindesk.com/arc/outboundfeeds/rss/"
        req = request.Request(url, method='GET')
        req.add_header('User-Agent', 'Mozilla/5.0')
        with request.urlopen(req, timeout=10) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            items = root.findall('.//item')
            if not items: return ["No new messages."]
            titles = []
            for item in items[:3]: # Take the 3 most important news items
                title = item.find('title')
                if title is not None and title.text:
                    titles.append(title.text.strip())
            return titles # Return as a list for Dashboard layout
    except Exception as e:
        return [f"News error: {e}"]

def update_nexus(*args, **kwargs):
    current_time_dt = datetime.now(timezone.utc)
    current_time = current_time_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{current_time}] Starting Nexus data fusion with data freshness consideration...")

    news = fetch_crypto_news()

    macro_data = "No Macro report"
    macro_age_hours = 0
    if os.path.exists(MACRO_FILE):
        try:
            with open(MACRO_FILE, 'r') as f:
                x_json = json.load(f)
                macro_data = x_json.get('content', "Report empty")
                lu_str = x_json.get('last_update', current_time)
                try:
                    lu_dt = datetime.strptime(lu_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                    macro_age_hours = (current_time_dt - lu_dt).total_seconds() / 3600
                except: macro_age_hours = 0
        except: pass

    # Get technical context from bot learning (v23.2)
    tech_context = "No technical data"
    learn_path = os.path.join(BASE_DIR, 'autonomic_learning.json')
    if os.path.exists(learn_path):
        try:
            with open(learn_path, 'r') as f:
                l_data = json.load(f)
                tech_context = json.dumps(l_data.get('macro_map', {}), indent=2)
        except: pass

    video_data = "No new video analysis"
    video_sentiment = "NEUTRAL"
    video_certainty = 5
    video_key_levels = []

    if os.path.exists(VIDEO_INTEL_FILE):
        try:
            with open(VIDEO_INTEL_FILE, 'r') as f:
                v_json = json.load(f)
            if isinstance(v_json, list) and len(v_json) > 0:
                sentiments = [item.get('sentiment', 'neutral') for item in v_json if isinstance(item, dict)]
                bull = sentiments.count('bullish')
                bear = sentiments.count('bearish')
                neu  = sentiments.count('neutral')
                dominant = 'BULLISH' if bull > bear and bull > neu else ('BEARISH' if bear > bull and bear > neu else 'NEUTRAL')
                video_sentiment = dominant
                summaries = [item.get('analysis', '') for item in v_json if isinstance(item, dict) and item.get('analysis')]
                video_data = f"Analysis of {len(v_json)} projects | Dominant sentiment: {dominant} ({bull}B/{bear}Be/{neu}N). " + " | ".join(summaries[:3])
                video_certainty = 8
            elif isinstance(v_json, dict):
                video_data = v_json.get('analysis', "Analysis available")
                video_sentiment = v_json.get('sentiment', "NEUTRAL").upper()
                video_certainty = v_json.get('confidence', v_json.get('certainty', 7))
                video_key_levels = v_json.get('key_levels', [])

            dash_video_data = {
                "sentiment": video_sentiment,
                "analysis": video_data,
                "certainty": video_certainty,
                "key_levels": video_key_levels,
                "time": datetime.now().strftime('%H:%M:%S')
            }
            try:
                with open(os.path.join(BASE_DIR, 'video_intel_dash.json'), 'w', encoding='utf-8') as f_dash:
                    json.dump(dash_video_data, f_dash, ensure_ascii=False, indent=4)
            except: pass
        except Exception as e:
            print(f"[NEXUS] Video Intel read error: {e}")

    prompt = f"""
    You are the Lead Crypto Strategist (Antigravity AI). Determine the NEXUS SCORE (0.0 - 10.0) based on the provided data.
    
    DATA HIERARCHY SYSTEM (VERY IMPORTANT):
    1. MACRO Report is {macro_age_hours:.1f} hours old. If age > 48h, its weight must be drastically reduced.
    2. FRESH NEWS (RSS) and TECHNICAL CONTEXT (Prices/ADX/Elliott Wave) have the highest priority.
    3. If ADX > 40 or a strong TRENDING regime exists, technicals have 80% weight over old macro.
    
    MARKET DATA:
    - NEWS (Fresh): {news}
    - MACRO REPORT (Age: {macro_age_hours:.1f}h): {macro_data}
    - TECHNICAL CONTEXT (LIVE): {tech_context}
    - VIDEO ANALYSIS (Sentiment {video_sentiment}): {video_data}

    HARD LOGIC RULE - STRICTLY FOLLOW:
    - macro_bias MUST correspond to nexus_score: (<4.5 Bearish, 4.5-5.5 Neutral, >5.5 Bullish).

    Return ONLY valid JSON:
    {{
      "nexus_score": 5.0,
      "macro_bias": "NEUTRAL",
      "test_action": "NONE",
      "onchain_risk": "MEDIUM",
      "ai_comment": "Short verdict (in English) + test info.",
      "sub_scores": {{
        "news_score": 5.0,
        "macro_score": 5.0,
        "video_score": 5.0
      }}
    }}
    """

    # Optimization v23.3: Dynamic cache key (refresh every 30 min or on version change)
    cache_ver = "v24_freshness"
    cache_time_block = int(time.time() / 1800)
    resp = ai_gateway.generate_content(
        prompt, 
        response_mime='application/json', 
        cache_key=f'nexus_macro_{cache_ver}_{cache_time_block}',
        cooldown=1800
    )

    if resp:
        try:
            new_state = json.loads(resp)

            # Safety fallback for sub_scores
            if "sub_scores" not in new_state:
                new_state["sub_scores"] = {"news_score": 5.0, "macro_score": 5.0, "video_score": 5.0}

            score = float(new_state.get("nexus_score", 5.0))
            
            # --- SANITY CHECK (v23.3) ---
            # If all sub-scores are low but score is high, correct it
            subs = new_state.get("sub_scores", {})
            avg_sub = sum(subs.values()) / len(subs) if subs else 5.0
            if avg_sub < 4.0 and score > 5.5:
                print(f"[NEXUS] SANITY: Score {score} conflicts with sub-scores ({avg_sub:.1f}). Correcting to {avg_sub:.1f}")
                score = avg_sub
                new_state["nexus_score"] = round(score, 1)

            if score > 5.5: new_state["macro_bias"] = "BULLISH"
            elif score < 4.5: new_state["macro_bias"] = "BEARISH"
            else: new_state["macro_bias"] = "NEUTRAL"

            new_state["last_ai_update"] = current_time
            new_state["gmail_intel"] = macro_data
            new_state["video_intel"] = video_data
            
            if telegram_reader and hasattr(telegram_reader, 'channel_signals'):
                 new_state["tg_signals_count"] = len(telegram_reader.channel_signals)

            # --- START: DASHBOARD TILES DATA DUMP ---
            try:
                # 1. RSS Tile (Only messages and AI verdict)
                rss_news_list = [
                    f"AI Verdict: {new_state.get('ai_comment', 'No comment')}"
                ]
                if isinstance(news, list):
                    rss_news_list.extend([str(n) for n in news[:2]])
                elif isinstance(news, str) and len(news) > 5:
                    rss_news_list.append(news[:100] + "...")

                rss_dashboard_data = {
                    "time": datetime.now().strftime('%H:%M:%S'),
                    "sentiment": new_state.get("macro_bias", "NEUTRAL").lower(),
                    "news": rss_news_list
                }
                with open(os.path.join(BASE_DIR, 'rss_intel.json'), 'w', encoding='utf-8') as f:
                    json.dump(rss_dashboard_data, f, ensure_ascii=False, indent=4)

                # 2. Fusion Tile (Nexus SubScores)
                sub = new_state.get("sub_scores", {})
                total_sub = sum(sub.values()) if sum(sub.values()) > 0 else 1

                fusion_dashboard_data = {
                    "total": int(new_state.get("nexus_score", 5.0) * 10),
                    "weights": {
                        "video": int((sub.get("video_score", 0) / total_sub) * 100),
                        "email": int((sub.get("macro_score", 0) / total_sub) * 100),
                        "tg": int((sub.get("news_score", 0) / total_sub) * 100)
                    }
                }
                with open(os.path.join(BASE_DIR, 'fusion_intel.json'), 'w', encoding='utf-8') as f:
                    json.dump(fusion_dashboard_data, f, ensure_ascii=False, indent=4)
            except Exception as d_err:
                print(f"[DASHBOARD EXPORT] Tile dump error: {d_err}")
            # --- END DUMP ---

            # [v22.8.1] MERGE LOGIC: Preserve portfolio data (balance, open_trades) when overwriting AI state
            final_state = new_state
            try:
                if os.path.exists(STATE_FILE):
                    with open(STATE_FILE, 'r', encoding='utf-8') as f:
                        old_state = json.load(f)
                        # Copy trading data if it exists in the old file
                        keys_to_preserve = ["balance", "open_trades", "last_update"]
                        for key in keys_to_preserve:
                            if key in old_state and key not in new_state:
                                final_state[key] = old_state[key]
            except Exception as m_err:
                print(f"[NEXUS] State merge error: {m_err}")

            import tempfile
            try:
                # [v22.8.2] ATOMIC WRITE: Prevents file corruption
                with tempfile.NamedTemporaryFile('w', dir=BASE_DIR, delete=False, encoding='utf-8') as tf:
                    json.dump(final_state, tf, indent=4, ensure_ascii=False)
                    temp_name = tf.name
                os.replace(temp_name, STATE_FILE)
            except Exception as w_err:
                print(f"[NEXUS] Critical state write error: {w_err}")

            print(f"[{current_time}] Success. Score: {final_state['nexus_score']} | Bias: {final_state['macro_bias']}")
        except Exception as e:
            print(f"[NEXUS] JSON write error: {e}")
