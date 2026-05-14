import os
import asyncio
import json
from telethon import TelegramClient, events
from dotenv import load_dotenv
import ai_gateway

# Configuration
load_dotenv()
API_ID = int(os.getenv("TG_API_ID", 0))
API_HASH = os.getenv("TG_API_HASH", "")
SESSION_NAME = 'antigravity_video'
DOWNLOAD_DIR = '/tmp/tg_videos'
# Set paths to the directory where the script is currently located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INTEL_FILE = os.path.join(BASE_DIR, 'video_intel.json')
LAST_ID_FILE = os.path.join(BASE_DIR, 'video_last_id.txt')
TARGET_CHANNEL = os.getenv("TG_VIDEO_CHANNEL", "YOUR_VIP_CHANNEL")

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Global client to avoid "database is locked"
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

async def process_video(file_path):
    print(f"[VIDEO BRIDGE] AI analysis for: {file_path}")
    prompt = """
    You are a market strategist. Analyze the trading video.
    JSON format: { "sentiment": "bullish/bearish/neutral", "confidence": 0-10, "analysis": "description", "key_levels": [] }
    """
    try:
        # Utilizing Gemini 2.5 Flash via AI Gateway
        analysis_json = ai_gateway.upload_and_analyze_video(file_path, prompt)
        if analysis_json:
            with open(INTEL_FILE, 'w', encoding='utf-8') as f:
                f.write(analysis_json)
            print(f"[VIDEO BRIDGE] Analysis saved.")
    except Exception as e:
        print(f"[VIDEO BRIDGE] AI Gateway error: {e}")

async def check_for_new_videos():
    """Checks history (used at startup and periodically)"""
    try:
        target_entity = await client.get_entity(TARGET_CHANNEL)
        last_id = 0
        if os.path.exists(LAST_ID_FILE):
            with open(LAST_ID_FILE, 'r') as f:
                try: 
                    content = f.read().strip()
                    last_id = int(content) if content else 0
                except: 
                    last_id = 0

        print(f"DEBUG: Scanning channel {TARGET_CHANNEL}. Last ID in DB: {last_id}")

        async for message in client.iter_messages(target_entity, limit=20):
            # Check if it's a video or a video document
            is_video = message.video or (message.document and message.document.mime_type and message.document.mime_type.startswith('video/'))
            
            if is_video and message.id > last_id:
                print(f"[VIDEO BRIDGE] NEW VIDEO FOUND! ID: {message.id}")
                path = await message.download_media(DOWNLOAD_DIR)
                
                if path:
                    await process_video(path)
                    if os.path.exists(path): 
                        os.remove(path)
                    
                    with open(LAST_ID_FILE, 'w') as f: 
                        f.write(str(message.id))
                    
                    print(f"[VIDEO BRIDGE] Success. ID {message.id} saved as last.")
                    break # Analyze only the newest video to avoid API overload
            else:
                msg_type = "VIDEO" if is_video else "TEXT/OTHER"
                print(f"DEBUG: Message {message.id} ({msg_type}) – skipping (ID <= {last_id} or no video).")

    except Exception as e:
        print(f"[VIDEO BRIDGE] Check error: {e}")
        import traceback
        traceback.print_exc()

async def main(daemon=False):
    print(f"[VIDEO BRIDGE] Initializing... Mode: {'DAEMON' if daemon else 'ONE-SHOT'}")

    # Connect ONCE
    await client.start()

    if not daemon:
        await check_for_new_videos()
    else:
        print("[VIDEO BRIDGE] Listening and scanning every 1h...")
        target_entity = await client.get_entity(TARGET_CHANNEL)

        # React immediately to new messages
        @client.on(events.NewMessage(chats=target_entity))
        async def handler(event):
            if event.message.video:
                print("[VIDEO BRIDGE] Captured new video from event!")
                await check_for_new_videos()

        # Simultaneously check every hour (in case event is missed)
        while True:
            await check_for_new_videos()
            await asyncio.sleep(3600)

async def run_daemon():
    """Wrapper function for DAEMON mode"""
    # client.start() is already called inside main()
    await main(daemon=True)
    await client.run_until_disconnected()

if __name__ == "__main__":
    import sys
    is_daemon = '--daemon' in sys.argv

    try:
        if is_daemon:
            # Use asyncio.run to create a new loop and run the client in it
            asyncio.run(run_daemon())
        else:
            asyncio.run(main(daemon=False))
    except KeyboardInterrupt:
        print("\n[VIDEO BRIDGE] Shutting down...")
