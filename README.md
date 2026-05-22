<div align="center">
  <h1>🛸 Antigravity AI Trading Agent</h1>
  <p><strong>An Autonomous, Multimodal Intelligence Sentinel for Cryptocurrency Markets</strong></p>

  <p>
    <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python Version" />
    <img src="https://img.shields.io/badge/version-v23.0.0%20Adaptive%20Intelligence-blueviolet.svg" alt="Version" />
    <img src="https://img.shields.io/badge/AI-Google%20Gemini%202.5%20Pro-orange.svg" alt="Google Gemini" />
    <img src="https://img.shields.io/badge/Exchange-Bybit%20Futures-black.svg" alt="Bybit" />
    <img src="https://img.shields.io/badge/Status-Active%20Development-success.svg" alt="Status" />
  </p>
</div>

<br />

## 📖 Overview

**Antigravity** is not just another trading bot—it is a sophisticated, self-contained algorithmic trading system designed to mimic the analytical workflow of a professional quantitative trader.

By fusing **real-time technical analysis** with **multimodal AI sentiment synthesis**, Antigravity parses unstructured data from the internet (Gmail macro reports, Telegram text signals, and even video analysis) to form a unified market worldview. It then autonomously executes and manages Futures trades on Bybit with strict risk management parameters.

This project was built to demonstrate advanced system architecture, asynchronous data processing, prompt engineering, and the practical application of LLMs (Large Language Models) in high-stakes environments.

---

## 🗓️ Changelog

### v23.0.0 — *Adaptive Intelligence* (2026-05-22)
> Major architectural overhaul — the bot now adapts to market conditions dynamically and learns from its own mistakes in a context-aware manner.

**New Modules:**
- **`circuit_breaker.py`** — Tracks consecutive losses per `(symbol, side)` pair. After 3 consecutive losses, trading on that pair is blocked for 4 hours. State is persistent via Redis (JSON fallback). Resets on a win.

**Core Engine (`autonomic_engine.py`):**
- **4-State Market Regime Classifier** — replaced binary EMA-based regime with a multi-factor classifier using ADX, ATR-ratio, and Bollinger Band Width: `TREND_UP | TREND_DOWN | RANGE_BOUND | VOLATILE_CHOP`
- **Dynamic ATR-Based SL/TP** — replaced fixed percentage bounds (0.5%–1.5%) with volatility-adaptive bounds: SL in `[1.5x, 3.0x ATR]`, TP minimum `2.25x ATR` (guarantees R:R ≥ 1.5)
- **Profit-First AI Prompt** — complete rewrite of the decision prompt with explicit tool inventory, conditional guidance per regime/RSI/ADX state, and a clear `MAKE MONEY. PROTECT CAPITAL.` prime directive
- **Context Enrichment at Entry** — saves Funding Rate and CVD-5min (Cumulative Volume Delta) alongside every trade open for higher-quality lesson extraction
- **Circuit Breaker Integration** — checks `circuit_breaker.is_blocked()` before every new entry; calls `record_win/record_loss` after every close
- **ATR values in AI prompt** — AI is shown exact `[SL_min, SL_max]` and `TP_min` in price units derived from current ATR

**Learning System (`ai_lesson_extractor.py`):**
- **Context-Aware Lesson Extraction** — lessons are now conditional rules tied to the specific market constellation at trade entry (regime, ADX, RSI, Nexus, SFP, CVD, funding rate)
- **Improved prompt format** — lessons shown to AI as `ONLY IF [conditions] → THEN [directive]` to prevent blind rule application across different market states
- **Lesson limit raised to 5** — AI now receives 5 recent lessons (up from 3) per evaluation cycle

---

### v22.3.0 — *Engine Optimizer* (2026-05-16)
- Enforced minimum R:R = 1.5 in code (not just in prompt)
- Lowered SL floor from 0.8% to 0.5%
- Hooked `trigger_lesson_extraction` into `bg_close_handler` (learning was previously broken — never triggered)
- Enriched trade context with RSI, ATR, EMA, ADX, SFP, Nexus Score, Symmetry, Wave Analysis at entry
- Fixed `get_closed_pnl` returning 0.0 USDT (wrong Bybit endpoint)
- Daily report now uses Bybit ground-truth data for active positions

---

### v22.0.0 — *Sentinel Protocol* (2026-04-08)
- Hardware relocation to Raspberry Pi 5
- Audit and reconciliation of SQLite ledger vs live Bybit trade history
- Gmail macro bridge OAuth re-authentication

---

## ✨ Key Features

### 🧠 Bring Your Own Intel (BYOI) Architecture
The system is built on a modular intelligence ingestion engine. It actively monitors, reads, and analyzes human-readable data sources:
- **Macro-Economic Analyst Bridge:** Connects via Google OAuth to Gmail to extract, read, and summarize premium weekly market reports.
- **Telegram Signal Scraper:** An asynchronous scraper that monitors public Telegram channels to extract community sentiment without requiring API access.
- **Video Analysis Bridge:** Uses Google Gemini to analyze market strategy videos shared on VIP Telegram channels, converting audiovisual insights into structured JSON data.

### 🌐 Data Nexus Fusion
Antigravity doesn't rely on a single metric. The **Data Nexus** aggregates Technical Analysis (RSI, EMA, ATR, ADX), AI-synthesized Macro Sentiment, and real-time Social Signals, assigning weighted scores to calculate an overall `Nexus Score` before taking any position.

### 🧬 Context-Aware Learning Engine
The bot self-optimizes. Every closed trade triggers `ai_lesson_extractor`, which uses the **full market state at entry** (regime, RSI, ADX, SFP, CVD, funding rate, Nexus) to generate a **conditional rule** — not a universal one. The AI learns that a pattern is a mistake *only in a specific constellation*, allowing it to short with confidence in the right conditions while avoiding the same pattern in others.

### 🔴 Circuit Breaker (v23.0)
After 3 consecutive Stop-Loss hits on the same `(symbol, side)` pair, the Circuit Breaker activates a 4-hour trading halt on that pair. This prevents the catastrophic loss patterns observed in the v22 audit (22 losses vs 8 wins). State survives engine restarts via Redis persistence.

### 📐 Dynamic ATR-Based Risk Management (v23.0)
Stop-Loss and Take-Profit distances are no longer static percentages. They are calculated as multiples of the current 15-minute ATR, ensuring that every position's SL is placed *outside the actual market noise* for that asset at that moment.

### 🛡️ Sentinel Protocol
Capital preservation is paramount. The system features a dedicated `bybit_gateway` monitoring thread that ensures every position is immediately wrapped in dynamic Stop-Loss and Take-Profit orders, preventing liquidations during sudden API disconnects or flash crashes.

### 🖥️ Real-time Mission Control Dashboard
Includes a sleek, responsive, Dark Mode Web Dashboard built with Flask and Vanilla JS. It provides real-time visibility into the bot's heartbeat, active trades, historic PnL, AI sentiment reasoning, and systemic logs.

---

## 🏗️ System Architecture

| Module | Role |
|:---|:---|
| `autonomic_engine.py` | Central heartbeat — data fusion, AI evaluation, trade execution, lifecycle management |
| `bybit_gateway.py` | Exchange API wrapper — orders, positions, WebSocket streams |
| `circuit_breaker.py` | **[NEW v23]** Consecutive-loss guard — blocks overtrading after repeated failures |
| `ai_lesson_extractor.py` | Post-trade AI reflection — generates conditional trading rules from closed trades |
| `gmail_intel_bridge.py` | Gmail OAuth bridge — reads macro analyst reports |
| `telegram_reader.py` | Async Telegram scraper — community sentiment signals |
| `bot_memory.py` | SQLite persistence — trades, lessons, decisions, market cache |
| `dashboard.py` | Flask web server — real-time visual interface |
| `cloud_backup.py` / `cloud_restore.py` | GCS disaster recovery — nightly snapshots |
| `version.py` | Centralized version management |

---

## 🛠️ Technology Stack

- **Core Engine:** Python 3.13 (Asynchronous processing, multi-threading, WebSocket)
- **AI Integration:** Google GenAI SDK (Gemini 2.5 Pro for decisions, Flash for sentiment)
- **Exchange Gateway:** Bybit V5 API + WebSocket Private Streams
- **Data Integrations:** Telethon (Telegram API), Google API Client (Gmail OAuth)
- **Data Persistence:** SQLite3 (Trade Ledgers, Lessons), Redis (Circuit Breaker state, caching), JSON (Dynamic configs)
- **User Interface:** Flask, HTML5, CSS3, JavaScript (Real-time polling)
- **Cloud Backup:** Google Cloud Storage (automated nightly snapshots with 7-day retention)
- **Hardware:** Raspberry Pi 4 (4GB RAM, 64GB SD)

---

## ☁️ Cloud Backup & Disaster Recovery

Antigravity includes a built-in automated backup system that snapshots all critical data (database, config, OAuth tokens, Telegram sessions) to **Google Cloud Storage** every night at 3:00 AM. In the event of hardware failure, the entire system can be restored on a new machine in minutes.

### Setting Up Google Cloud Storage (one-time)

**Step 1 — Create a Storage Bucket:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/) and select your project.
2. Search for **Cloud Storage → Buckets** and click **Create**.
3. Choose a unique name (e.g. `my-antigravity-backup`).
4. Select a **Region** — for the free tier choose `us-central1`, `us-east1`, or `us-west1`.
5. Leave *Storage class* as **Standard** and click **Create**.

> **Cost:** Google's Always Free tier includes **5 GB** of Standard storage in US regions. With daily compressed snapshots (~10 MB each) and 7-day retention, you will use less than 100 MB — **completely free**.

**Step 2 — Create a Service Account (API key for the bot):**
1. Search for **IAM & Admin → Service Accounts** and click **Create Service Account**.
2. Name it (e.g. `backup-bot`) and click *Create and Continue*.
3. Assign the role: **Cloud Storage → Storage Object Admin**.
4. Click *Done*, then open the new account → **Keys** tab → **Add Key → Create new key → JSON**.
5. Save the downloaded `.json` file as `gcp-backup-key.json` in your project root.

**Step 3 — Configure environment:**
```bash
# In your .env file, add:
GCP_BUCKET_NAME=your-bucket-name
```

> ⚠️ Never commit `gcp-backup-key.json` to Git — it is already excluded in `.gitignore`.

For full backup and restore instructions, see [**CLOUD_BACKUP_GUIDE.md**](CLOUD_BACKUP_GUIDE.md).

---

## 🔧 Disaster Recovery (New Hardware)

If your server fails, restoring to a fresh machine takes a single command on your local PC:

```bash
bash setup_pi.sh
```

This script will automatically configure SSH access, set the hostname, install all dependencies, clone this repository, restore your latest cloud backup, and start all services. **No manual steps required.**

---

## 🚀 Getting Started

Want to deploy Antigravity yourself? The repository is built as an open-source template.

Please refer to the comprehensive [**Template Setup Guide**](TEMPLATE_SETUP_GUIDE.md) for step-by-step instructions on configuring your `.env` file, obtaining the necessary API keys, generating OAuth tokens, and starting the engine.

> **Note:** The bot runs in `Testnet` mode by default to ensure safe exploration of the codebase.

---

## ⚠️ Disclaimer

This software is for educational and portfolio demonstration purposes only. Cryptocurrency futures trading carries a high level of risk and may not be suitable for all investors. The author is not responsible for any financial losses incurred from deploying this software.

---

<div align="center">
  <p><i>Engineered with precision. Designed for the future of autonomous finance.</i></p>
  <p><b>Mateusz Nowak [mateusznowak.x]</b></p>
</div>
