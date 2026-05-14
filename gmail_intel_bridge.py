import os
import json
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
import ai_gateway

# Load .env (API Keys)
load_dotenv()

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MACRO_FILE = os.path.join(BASE_DIR, 'macro_intel.json')

def extract_intel_from_gmail():
    """Searches Gmail for the latest Macro Analyst report and updates macro_intel.json"""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("[GMAIL BRIDGE] Error: Google API libraries missing.")
        return False

    # Scopes for Gmail API
    SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
    creds = None

    # Standard path to token and credentials
    token_path = os.path.join(BASE_DIR, 'token.json')
    creds_path = os.path.join(BASE_DIR, 'credentials.json')

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(creds_path):
                print(f"[GMAIL BRIDGE] Error: File {creds_path} missing. Download it from Google Cloud Console.")
                return False
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            print("\n[GMAIL BRIDGE] Headless Mode (Port 8080):")
            print("1. Open a NEW terminal on your computer and type: ssh -L 8080:localhost:8080 user@your-server-ip")
            print("2. Copy the link below to your browser:")
            creds = flow.run_local_server(port=8080, open_browser=False)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('gmail', 'v1', credentials=creds)

        # Configurable query from .env
        query = os.getenv("GMAIL_QUERY", "from:newsletter@example.com subject:\"Market Report\"")
        results = service.users().messages().list(userId='me', q=query, maxResults=1).execute()
        messages = results.get('messages', [])

        source_name = os.getenv("GMAIL_SOURCE_NAME", "YOUR_MACRO_SOURCE")

        if not messages:
            print(f"[GMAIL BRIDGE] No messages found for query: {query}")
            return False

        message_id = messages[0]['id']
        msg = service.users().messages().get(userId='me', id=message_id, format='full').execute()
        
        # --- Real date from Google servers ---
        internal_date_ms = int(msg['internalDate'])
        real_iso_date = datetime.fromtimestamp(internal_date_ms / 1000.0, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        # Extracting body (simplified)
        parts = msg['payload'].get('parts', [])
        body = ""
        if not parts:
            import base64
            body = base64.urlsafe_b64decode(msg['payload']['body']['data']).decode('utf-8')
        else:
            for part in parts:
                if part['mimeType'] == 'text/plain':
                    import base64
                    body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                    break

        if not body:
            print("[GMAIL BRIDGE] Failed to extract email content.")
            return False

        # Use Gemini for synthesis (via ai_gateway)
        print(f"[GMAIL BRIDGE] Email found (ID: {message_id}). Sending to Gemini...")

        prompt = f"""
You are a macro analyst for the Antigravity system. Below is the content of an email with a weekly market report from Macro Analyst (Macro Source).
Extract the most important macro facts, technical levels for BTC/ETH/SOL/LINK, and general sentiment.
Focus on specifics (numbers, events, threats).
The result must be concise (max 600 characters) and in English.

EMAIL CONTENT:
{body}

ANSWER ONLY IN JSON FORMAT:
{{
    "content": "Your synthesis here"
}}
"""

        # Use dynamic cache key based on email ID
        ai_resp = ai_gateway.generate_content(
            prompt=prompt,
            response_mime='application/json',
            cache_key=f'gmail_macro_{message_id}',
            cooldown=86400
        )

        if ai_resp:
            intel_data = json.loads(ai_resp)
            intel_data["source"] = source_name
            intel_data["last_update"] = real_iso_date

            with open(MACRO_FILE, 'w', encoding='utf-8') as f:
                json.dump(intel_data, f, indent=4, ensure_ascii=False)

            print(f"[GMAIL BRIDGE] Success! Intel updated: {intel_data['last_update']}")
            return True

    except Exception as e:
        print(f"[GMAIL BRIDGE] Critical error: {e}")
        return False

if __name__ == "__main__":
    extract_intel_from_gmail()
