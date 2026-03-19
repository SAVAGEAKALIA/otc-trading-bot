# OTC BOT

A modular, multi-threaded, asynchronous trading engine designed for high-performance Binary Options trading on IQ Option OTC.

---

## Project Architecture

```text
IQoption/
├── iqoption_bot/           # CORE BOT LOGIC
│   ├── strategies/         # Strategy Encyclopedia (13+ Algorithms)
│   ├── analytics.py        # Indicator Engine & Quality Filters
│   ├── bot.py              # Main Orchestrator
│   ├── scanner.py          # Autonomous OTC Universe Scanner
│   ├── worker.py           # IQ Option API Wrapper & Heartbeat
│   ├── strategy_engine.py  # Weighted Voting & Performance Tracking
│   ├── sizing.py           # Fractional Kelly & Risk Engine
│   └── ...                 # Helpers (Parser, Session, Logging)
├── iqoptionapi/            # Protocol Implementation
├── data/                   # JSON Persistence (Trade Logs, ML Models)
├── main.py                 # Main Entry Point
├── otc-bot.py              # Dedicated OTC Scanner Entry
├── Dockerfile              # Containerized Deployment
└── .env.example            # Environment Template
```

---

## Component Technical Map

| Module | Role | Technical Responsibility |
| :--- | :--- | :--- |
| **`worker.py`** | **The Heart** | Manages WebSocket connections, candle streaming, and the 30-minute Heartbeat telemetry. |
| **`scanner.py`** | **The Eye** | Scans 66+ OTC pairs in parallel. Implements the "Second 58" precision timing rule. |
| **`strategy_engine.py`** | **The Brain** | Performs weighted voting between strategies. Adjusts weights dynamically based on real-time win rates. |
| **`analytics.py`** | **The Filter** | Calculates oscillators (Wilder RSI, EMA MACD) and enforces the "Guardian" Hard Gates. |
| **`sizing.py`** | **The Wallet** | Implements the **Fractional Kelly Criterion** for optimal capital allocation. |
| **`bot.py`** | **The Captain** | Coordinates between the Telegram Listener, Scanner, and Trade Queue. |

---

## Strategy Encyclopedia
The bot employs 13+ distinct trading logics, which can be run in **Voting** or **Tournament** mode.

*   **MHI Strategy**: Based on the "Most High Index" candle pattern, focusing on color dominance in 3-candle sequences.
*   **CCV2 Strategy**: A custom confluence of momentum indicators tailored for OTC reversals.
*   **Indicator Strategy**: A pure technical approach using weighted RSI, MACD, and Stochastic Alignment.
*   **Squeeze Breakout**: Monitors the Bollinger Band / Keltner Channel squeeze for high-volatility breakouts.
*   **Exhaustion Fade**: Detects "stretched" price action and fades the move back to the EMA mean.
*   **Late Candle Sniper**: Filters for setups that only become high-probability in the final 10 seconds of a candle.
*   **Adaptive Strategy**: Adjusts its internal thresholds based on the detected Volatility Regime (Low, Normal, High, Extreme).

---

## 🛡️ The "Guardian" Quality Overlay
Every signal is passed through data-proven "Hard Gates" to filter out low-probability "OTC Traps":

| Guardian | Quantitative Rule | Why it Exists |
| :--- | :--- | :--- |
| **Expansion Trap** | `Current Body > 1.2x Previous` | Prevents "chasing" a move that has already exhausted its energy. |
| **Wick Magnet** | `Rejection Wick > 40%` | Rejects messy candles where price is already being pushed back. |
| **RSI Extreme** | `RSI < 30 or > 70` | Prevents trading at the very end of an over-extended trend. |
| **Calm Confluence** | `2m/5m/15m Trend Alignment` | Enforces trading with the larger market flow (58.7% WR basis). |

---

## Capital Management & Risk

### 1. Fractional Kelly Criterion
The bot uses a **¼ Kelly** (or custom fraction) to calculate trade size:
`Bet Size = (Win% - (Loss% / Odds)) * Fraction`
This ensures the bot grows the account exponentially during winning streaks while aggressively protecting the balance during drawdowns.

### 2. Session Safety Locks
- **Daily Stop-Loss**: Total account protection.
- **Consecutive Loss Cooldown**: Pauses trading after 3 losses to wait for market regime changes.
- **Profit Target**: Automatically locks in gains once the target is reached.

---

## Telegram Administration (Self-Bot)
Interact with the bot in any Telegram chat to manage your session:

*   `/status`: Instant dashboard (Balance, PnL, Payouts).
*   `/scanner top 10`: Focus the scanner on the 10 most "stable" OTC pairs.
*   `/stats`: View the win rate breakdown of every active strategy.
*   `/heartbeat`: Force a 30-minute market stagnation report.
*   `/pause` / `/resume`: Safety switch for all trading activity.

---

## ⚙️ The Definitive `.env` Index

| Group | Key | Typical Value |
| :--- | :--- | :--- |
| **IQ Account** | `IQ_ACCOUNT_TYPE` | `PRACTICE` or `REAL` |
| **Sizing** | `SIZING_KELLY_FRACTION` | `0.25` (¼) or `0.125` (⅛) |
| **Scanner** | `CONFIDENCE_MIN` | `0.65` (Min score for entry) |
| **Scanning** | `SCANNER_INTERVAL` | `10` (Seconds between scan cycles) |
| **Strategy** | `MIN_AGREEMENT` | `2` (Min num strategies that must agree) |
| **Timing** | `CLOSE_WINDOW_SEC` | `10` (Scan window near candle close) |

---

## 🚀 Deployment & Troubleshooting

### Docker Deployment
1.  Configure `.env` using `.env.example`.
2.  `docker compose up -d --build`
3.  **Telegram SMS Login**: Run `docker compose run --rm otc-bot` and enter your login code.

### Troubleshooting
- **Websocket Errors**: The bot will automatically attempt to reconnect. If it fails, check your API credentials.
- **SMS Login**: If you don't receive a code, ensure your Telegram API ID and Hash are correct.
- **Stale Market**: If the log shows `⚠️ Stale Market Witnessed`, it means IQ Option isn't sending new price data. The bot will wait for fresh data before resuming.

---
**Built by Saviour**

> **WARNING**: Trading involves significant risk. This platform is provided for research and automation purposes. **Do not trade what you cannot afford to lose.**
