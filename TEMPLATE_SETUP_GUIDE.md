# 🌌 Antigravity Trading Bot - Template Setup Guide

This document describes how to configure the Antigravity AI trading bot from this template. The bot integrates technical analysis, media sentiment (Gmail, Telegram, Video), and the Gemini language model to make autonomous trading decisions on the Bybit exchange.

## 🛠 Prerequisites
1. **Python 3.10+**
2. **Redis Server** (for Nexus data caching)
3. **Bybit Account** (with API enabled and Futures trading permissions)
4. **Google Cloud Account** (for Gemini API and Gmail access)
5. **Telegram API Account** (for scraping signals and notifications)

---

## 🚀 Step-by-Step Setup

### 1. Environment Configuration (.env)
Rename `.env.example` to `.env` (make sure to remove the `.example` extension) and fill in the following fields:
- `GEMINI_API_KEY`: Generate your key in Google AI Studio.
- `TELEGRAM_TOKEN`: Obtain from @BotFather.
- `TELEGRAM_CHAT_ID`: The chat ID where the bot should send reports.
- `TG_API_ID` & `TG_API_HASH`: Obtain at [my.telegram.org](https://my.telegram.org).
- `BYBIT_API_KEY` & `BYBIT_API_SECRET`: API keys from your Bybit account (for main trading engine).

### 2. Google Authorization (Gmail Bridge)
The bot requires access to Gmail to read macro reports:
1. Download the `credentials.json` file from your Google Cloud Console (OAuth 2.0 Client ID) or rename the provided `credentials.json.example` to `credentials.json` and fill in your details.
2. Place it in the root directory of the project.
3. On the first run, `gmail_intel_bridge.py` will open a browser for authorization. The `token.json` file will be generated automatically.

### 3. Telegram Authorization (Video/Signal Bridge)
To enable the bot to read messages from Telegram channels:
1. Run the session configuration script:
   ```bash
   python3 setup_telegram.py
   ```
2. Follow the terminal instructions (enter phone number and code). The `antigravity_video.session` file will be created.

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Running the Bot
Main Engine:
```bash
python3 autonomic_engine.py
```
Dashboard (Optional):
```bash
python3 dashboard.py
```
Once the Dashboard is running, you can access it by opening your web browser and navigating to `http://localhost:5000`. If you are running the bot on a remote server (e.g., Raspberry Pi or VPS), use `http://YOUR_SERVER_IP:5000`.

### 6. Customizing Nexus Sources (Optional)
By default, the bot is configured with placeholders for Gmail and Telegram sources. You can change these in `.env`:
- `GMAIL_QUERY`: Change to a query matching your newsletters (e.g., `from:newsletter@example.com subject:Report`).
- `GMAIL_SOURCE_NAME`: Descriptive name of your source.
- `TG_CHANNEL_URL`: Change to any public channel in the format `https://t.me/s/CHANNEL_NAME`. The bot will automatically adapt its scraper to the new source.
- `TG_VIDEO_CHANNEL`: The private/VIP channel to monitor for video analysis (used by video bridge).

---

## 📁 File Structure
- `autonomic_engine.py`: The main brain of the bot (heartbeat, AI logic).
- `autonomic_learning.json`: Technical parameters (ATR, RSI, EMA) subject to self-learning.
- `bybit_gateway.py`: Exchange communication layer.
- `memory.py`: SQLite database and Redis cache handler.
- `macro_intel.json`: Current "intelligence" state of the bot (data fusion).

---

## ⚠️ Important Notes
- **Testnet**: By default, `.env` is set to `IS_BYBIT_TESTNET=True`. Change to `False` only after thorough testing.
- **Security**: Never share `.env`, `credentials.json`, `token.json`, or `*.session` files publicly.
- **Risk**: You use this bot at your own risk. Cryptocurrency trading involves a high risk of capital loss.
