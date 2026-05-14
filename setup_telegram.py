import os
import asyncio
from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv()
API_ID = int(os.getenv("TG_API_ID", 0))
API_HASH = os.getenv("TG_API_HASH", "")
SESSION_NAME = 'antigravity_video'

async def main():
    if not API_ID or not API_HASH:
        print("Error: Add TG_API_ID and TG_API_HASH to the .env file")
        return

    print("--- TELEGRAM SESSION Configuration ---")
    print(f"API_ID: {API_ID}")
    
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start() # This will trigger interactive login (phone number, SMS/2FA code)
    
    if await client.is_user_authorized():
        print("\n✅ SUCCESS! Session has been saved.")
        print(f"Session file: {SESSION_NAME}.session")
        me = await client.get_me()
        print(f"Logged in as: {me.first_name} (@{me.username})")
    else:
        print("\n❌ Authorization error.")
    
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
