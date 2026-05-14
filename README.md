<div align="center">
  <h1>🛸 Antigravity AI Trading Agent</h1>
  <p><strong>An Autonomous, Multimodal Intelligence Sentinel for Cryptocurrency Markets</strong></p>

  <p>
    <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python Version" />
    <img src="https://img.shields.io/badge/AI-Google%20Gemini%202.5%20Flash-orange.svg" alt="Google Gemini" />
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

## ✨ Key Features

### 🧠 Bring Your Own Intel (BYOI) Architecture
The system is built on a modular intelligence ingestion engine. It actively monitors, reads, and analyzes human-readable data sources:
- **Macro-Economic Analyst Bridge:** Connects via Google OAuth to Gmail to extract, read, and summarize premium weekly market reports.
- **Telegram Signal Scraper:** An asynchronous scraper that monitors public Telegram channels to extract community sentiment without requiring API access.
- **Video Analysis Bridge:** Uses Google Gemini to analyze market strategy videos shared on VIP Telegram channels, converting audiovisual insights into structured JSON data.

### 🌐 Data Nexus Fusion
Antigravity doesn't rely on a single metric. The **Data Nexus** aggregates Technical Analysis (RSI, EMA, ATR), AI-synthesized Macro Sentiment, and real-time Social Signals, assigning weighted scores to calculate an overall `Market Readiness Score` before taking any position.

### 🧬 Autonomic Learning Engine
The bot self-optimizes. By logging every trade's outcome into a persistent SQLite ledger, the system periodically analyzes its own win-rate. It dynamically adjusts its technical tolerances (e.g., modifying the RSI trigger threshold or ATR multiplier) to adapt to changing market regimes (Bull, Bear, Choppy).

### 🛡️ Sentinel Protocol
Capital preservation is paramount. The system features a dedicated `binance_algo_bridge` / `bybit_gateway` monitoring thread that ensures every position is immediately wrapped in dynamic Stop-Loss and Take-Profit orders, preventing liquidations during sudden API disconnects or flash crashes.

### 🖥️ Real-time Mission Control Dashboard
Includes a sleek, responsive, Dark Mode Web Dashboard built with Flask and Vanilla JS. It provides real-time visibility into the bot's heartbeat, active trades, historic PnL, AI sentiment reasoning, and systemic logs.

---

## 🛠️ Technology Stack

- **Core Engine:** Python (Asynchronous processing, multi-threading)
- **AI Integration:** Google GenAI SDK (Gemini 2.5 Flash for text and video analysis)
- **Exchange Gateway:** Bybit V5 API
- **Data Integrations:** Telethon (Telegram API), Google API Client (Gmail)
- **Data Persistence:** SQLite3 (Trade Ledgers), JSON (Dynamic configurations)
- **User Interface:** Flask, HTML5, CSS3, JavaScript (Real-time polling)

---

## 🏗️ System Architecture

1. **`autonomic_engine.py`**: The central heartbeat. Manages data fusion, evaluates the Nexus score, executes trades, and updates the ledger.
2. **`bybit_gateway.py`**: The robust API wrapper handling exchange communication, signature generation, and order execution.
3. **`gmail_intel_bridge.py` & `telegram_reader.py`**: The external "eyes and ears" gathering unstructured data for AI synthesis.
4. **`dashboard.py`**: A lightweight web server providing a visual interface for the system's internal state.

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
