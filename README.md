# OTC BOT

> **Status (2026-10-30):** measured with no edge. 250 live trades won 53.2% against a 54.2% breakeven, and 1.27M OTC candles show no rule above 50.1%.
> Live trading is stopped pending a direction decision. See [docs/plans/2026-10-30-direction-reset.md](docs/plans/2026-10-30-direction-reset.md).
> Check any strategy or trade log with `python -m trading_platform.apps.edge_audit --help`.

A modular, multi-threaded, asynchronous trading engine designed for high-performance Binary Options trading on IQ Option OTC.

---

## Project Architecture

```text
IQoption/
├── trading_platform/       # CANONICAL PROJECT PACKAGE
│   ├── domain/              # Immutable domain contracts
│   ├── application/         # Ports and application services
│   ├── brokers/             # IQ Option, Bybit, simulated adapters
│   ├── execution/           # OMS and reconciliation
│   ├── risk/                # Deterministic risk engine
│   ├── storage/             # Ledger, outbox, migrations
│   ├── market_data/         # Market-data providers
│   ├── strategies/otc/      # OTC strategy implementations
│   ├── research/            # Training and artifact workflows
│   ├── interfaces/          # Operator interfaces
│   ├── apps/                # Application entry points
│   ├── legacy/iqoption_bot/ # Compatibility runtime during migration
│   ├── ml/                  # Shared ML compatibility exports
│   ├── configs/             # Platform configs
│   ├── scripts/             # Collectors and trainers
│   └── vendor/              # Vendored IQ Option client
├── backup/                  # Historical backups (kept at root)
│   ├── strategies/         # Legacy compatibility only
│   ├── analytics.py        # Indicator Engine & Quality Filters
│   ├── bot.py              # Main Orchestrator
│   ├── scanner.py          # Autonomous OTC Universe Scanner
│   ├── worker.py           # IQ Option API Wrapper & Heartbeat
│   ├── ml/                 # Shared causal telemetry/features
│   ├── strategy_engine.py  # Weighted Voting & Performance Tracking
│   ├── sizing.py           # Fractional Kelly & Risk Engine
│   └── ...                 # Helpers (Parser, Session, Logging)
├── data/                   # JSON Persistence (Trade Logs, ML Models)
├── tests/                  # Root-level test suite
├── docs/                   # Architecture and operations docs
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
| **`ML_LSTM`** | **ML Direction** | Proposes CALL/PUT from closed candles and causally available market context. |
| **Directional CatBoost** | **ML Direction** | Predicts the next exact 2m candle from enriched candle/context features. |
| **CatBoost gate** | **ML Selection** | Later scores an existing strategy candidate; never creates or reverses direction. |

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

See the complete, current [Telegram command reference](docs/telegram-commands.md)
for supported commands, safety constraints, and the verified-performance model.
The complete data, Kaggle training, artifact deployment, shadow validation, and
rollback flow is in the [enriched ML pipeline](docs/enriched-ml-pipeline.md).
The immediate candle-based workflow is in the
[directional CatBoost guide](docs/directional-catboost-training.md).

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
