import os
import json
import time
from google import genai
from google.genai import types

# Cache path
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ai_cache.json')

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache):
    """Saves cache and removes entries older than 24h (Optimization v22.4)"""
    try:
        now = time.time()
        # Clean old entries (> 24h)
        cleaned_cache = {k: v for k, v in cache.items() if (now - v.get('timestamp', 0)) < 86400}
        
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cleaned_cache, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[AI GATEWAY] Cache save error: {e}")

def get_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("[AI GATEWAY] GEMINI_API_KEY missing in environment!")
    return genai.Client(api_key=api_key)

def generate_content(prompt, model='gemini-2.5-flash', response_mime='text/plain', cache_key=None, cooldown=150, timeout=30):
    now = time.time()
    cache = load_cache()

    if cache_key and cache_key in cache:
        cached_item = cache[cache_key]
        if now - cached_item.get('timestamp', 0) < cooldown:
            return cached_item.get('response')

    try:
        client = get_client()
        print(f"[AI GATEWAY] Sending query to model {model} (SDK)... [Tokens Opt: active]")
        
        config = types.GenerateContentConfig(response_mime_type=response_mime)
        response = client.models.generate_content(model=model, contents=prompt, config=config)
        result = response.text.strip()
        
        if response_mime == 'application/json':
            if result.startswith("```json"):
                result = result[7:-3].strip()
            elif result.startswith("```"):
                result = result[3:-3].strip()

        if cache_key:
            cache[cache_key] = {'timestamp': now, 'response': result}
            save_cache(cache)
            
        return result

    except Exception as e:
        print(f"[AI GATEWAY] SDK Critical error: {e}")
        if cache_key and cache_key in cache:
            return cache[cache_key].get('response')
        return None

def upload_and_analyze_video(file_path, prompt):
    try:
        client = get_client()
        print(f"[AI GATEWAY] Uploading file to Google: {file_path}...")
        uploaded_file = client.files.upload(file=file_path)
        
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(2)
            uploaded_file = client.files.get(name=uploaded_file.name)
            
        print("[AI GATEWAY] Video processed. Analysis in progress...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[uploaded_file, prompt],
            config=types.GenerateContentConfig(response_mime_type='application/json')
        )
        return response.text
    except Exception as e:
        print(f"[AI GATEWAY] Video SDK error: {e}")
        return None
