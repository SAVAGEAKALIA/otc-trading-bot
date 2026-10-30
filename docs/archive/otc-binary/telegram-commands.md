# Telegram command reference

Only configured administrators can change execution settings. Commands without
an argument display their current setting where applicable. Runtime command
changes are not written to `.env`; record deliberate configuration changes in
the deployment configuration before restarting the bot.

## Safe operating sequence

1. Start with `/dryrun on`, `/scanner off`, and `/martingale off`.
2. Check `/account`, `/status`, `/session`, and `/scanner status`.
3. Keep `ALLOWED_TRADE_DURATIONS=2` until the bot has a sufficiently large
   broker-verified out-of-sample cohort.
4. Enable only one source at a time: `/telegram on` or `/scanner on`.
5. Use `/pause reason` before changing risk settings; use `/resume` only
   after reviewing `/stats` and `/breakdown`.

`/stats` and `/breakdown` intentionally use only version-2, broker-API
verified win/loss outcomes. Balance-derived, forced, legacy, pending, and
unknown outcomes remain in the ledger for audit but do not train the bot or
enter its win-rate calculation.

## Monitoring (available to permitted chat users)

| Command | Purpose |
|---|---|
| `/help` | Short in-chat command list. |
| `/myid` | Telegram user ID and admin status. |
| `/status` | Bot state, uptime, dry-run state, connection, and queue. |
| `/stats` | Verified win/loss/tie count, win rate, P&L, excluded and pending settlements. |
| `/breakdown` | Verified win rate by source, asset, and duration. |
| `/session` | Current session P&L, loss streak, and limits. |
| `/trades` | Positions waiting for settlement. |
| `/balance` | Current account balance. |
| `/account` | Account mode and balance. |
| `/patterns EURUSD-OTC` | Technical-pattern report for an asset. |
| `/fpstats` | Fingerprint database diagnostics. |
| `/cache` | Cache diagnostics. |
| `/weights` | Strategy performance weights. |

## Safety and session control (admin)

| Command | Purpose |
|---|---|
| `/pause [reason]` | Blocks new trades while monitoring continues. |
| `/resume` or `/start` | Clears a manual pause. |
| `/stop` | Stops the bot. |
| `/dryrun on\|off` | Simulate decisions without placing trades. |
| `/telegram on\|off` | Enable or disable Telegram-signal intake. |
| `/reset session\|scanner\|all` | Reset in-memory session metrics and/or scanner cooldowns. It does **not** erase the ledger. |
| `/session maxloss 50` | Set session loss stop in account currency. |
| `/session maxstreak 3` | Set the maximum consecutive-loss stop. |
| `/session target 100` | Set the session profit target. |
| `/account switch` | Toggle PRACTICE/REAL account mode. Verify `/account` immediately afterwards. |

## Position sizing (admin)

| Command | Purpose |
|---|---|
| `/sizing` | Show active sizing method and limits. |
| `/sizing fixed 5` | Fixed stake amount. |
| `/sizing percent 2` | Stake 2% of balance. |
| `/sizing kelly 0.25` | Use fractional Kelly. This remains neutral until verified history exists. |

## Martingale (admin)

Martingale is off by default. It increases loss exposure; it is not a
win-rate improvement mechanism. Keep it off during the clean validation
cohort.

| Command | Purpose |
|---|---|
| `/martingale` | Show status. |
| `/martingale on\|off` | Enable or disable recovery steps. |
| `/martingale steps 1` | Maximum recovery steps. |
| `/martingale multiplier 2.0` | Recovery stake multiplier. |
| `/martingale duration 2` | Recovery duration; it must be in `ALLOWED_TRADE_DURATIONS`. |
| `/martingale gatekeeper on\|off` | Enable/disable the dedicated recovery gatekeeper. |
| `/martingale_mode classic\|pullback` | Choose immediate or pullback-based recovery scheduling. |

## Gatekeeper (admin)

| Command | Purpose |
|---|---|
| `/gatekeeper` | Show risk-gate status. |
| `/gatekeeper on\|off` | Enable or bypass the gatekeeper. Do not use `off` in live trading. |
| `/gatekeeper mode strict\|normal\|relaxed\|very_relaxed` | Set gate strictness. |
| `/threshold scanner 80` | Set a manual scanner threshold. |
| `/threshold telegram 25` | Set a manual Telegram threshold. |
| `/threshold scanner none` | Remove a manual threshold override. |
| `/alphahours on\|off` | Enable or disable the time-of-day gate. Treat it as a hypothesis until verified forward results support it. |

## Scanner (admin)

The scanner uses broker-verified results for learning. In voting mode, its
agreement gate requires two independent strategy families by default: MHI,
Majority, R7, and CCV2 are one correlated candle-reversal family, not four
separate confirmations. Momentum Cascade and Compression Breakout are also
one price-continuation family. Tournament mode intentionally selects a single
strategy and does not provide voting confluence.

| Command | Purpose |
|---|---|
| `/scanner` or `/scanner status` | Full scanner state and active hard gates. |
| `/scanner on\|off` | Enable or disable scanner signal generation. |
| `/scanner mode single\|multi` | Limit concurrent scanner trades. |
| `/scanner profile trend\|reversal\|mixed` | Choose scan profile. |
| `/scanner strategy indicators` | Select one named strategy. |
| `/scanner strategy cascade+sniper+compression` | Select a custom voting combination. |
| `/scanner scan_mode voting\|tournament` | Voting requires agreement; tournament picks one candidate. |
| `/scanner agreement 2` | Minimum agreeing strategies in voting mode. It cannot bypass the independent-family gate. |
| `/scanner families 2` | Minimum independent evidence families in voting mode. |
| `/scanner interval 15` | Start-to-start cadence. If a scan takes longer, the next cycle starts after it completes. |
| `/scanner top 15` | Limit scan universe; `0` scans all available pairs. |
| `/scanner confidence 70` | Minimum scanner confidence, percentage or decimal. |
| `/scanner expiryconfluence 2` | Fast-expiry indicator-confluence threshold. `confluence` is an alias. |
| `/scanner timeframe fixed` | Use the current fixed duration. |
| `/scanner timeframe 2` | Set fixed scanner duration; it must be execution-whitelisted. |
| `/scanner timeframe dynamic` | Deliberately unavailable while the verified cohort is fixed-duration. |
| `/scanner maxduration 2` | Dynamic-mode maximum only; execution whitelist still wins. |
| `/scanner precision on\|off` | Toggle precision timing. |
| `/scanner autostop on\|off` | Stop scanner on a session-risk block. |
| `/scanner mlbypass on\|off` | Enable/disable the ML-only scanner hard-gate bypass. It applies when LSTM or directional CatBoost wins; strategy agreement, session limits, sizing, cooldowns, and execution safeguards still apply. |
| `/scanner mlthreshold 70` | Set the in-memory LSTM action threshold as a percentage or decimal. It resets on restart and does not change exported metadata. Use only for supervised practice validation. |
| `/scanner mlsignal lstm\|catboost\|both\|off` | Select registered directional ML models. Use `catboost` for the immediate candle model and keep the later candidate gate separate. |
| `/scanner mlgate off\|shadow\|enforce` | Control the conditional CatBoost gate. `shadow` logs decisions without filtering. `enforce` fails closed when artifacts/context are unavailable or the artifact is not offline-approved. |
| `/scanner mlpayout 75` | Set the minimum current payout accepted by the CatBoost gate. |
| `/scanner mledge 2` | Require at least 2% model-implied expected value after the current payout. |
| `/scanner rsiextreme on\|off` | Toggle the trend-strategy RSI-extreme block. Strategies defined by an RSI extreme keep their internal guards. |
| `/scanner expansion on\|off` | Toggle the continuation expansion-trap block. Breakout/exhaustion strategies keep their internal guards. |
| `/scanner wick on\|off` | Toggle directional-wick block. |
| `/scanner calmconfluence on\|off` | Toggle multi-timeframe alignment for trend-continuation strategies. |
| `/scanner quality on\|off` | Toggle the trend-continuation quality overlay. Reversal and breakout strategies use their own gates. |
| `/scanner qualitymin 50` | Minimum quality score, 0–100. |
| `/scanner putboost on\|off` | Toggle bearish-alignment boost. |
| `/scanner stoch on\|off` | Toggle stochastic tie-breaker. |
| `/scanner runcap 4` | Block extended same-direction runs; `0` disables it. |
| `/scanner regime on\|off` | Toggle ATR regime routing. |
| `/scanner blacklist` | Show low-performing assets from verified scanner outcomes. |
| `/scanner research` | Show settled paper outcomes by strategy, including shadow candidates rejected by voting or overlays. |
| `/scanner blacklist_min 12` | Sample size before automatic blacklisting. |
| `/scanner blacklist_rate 0.38` | Minimum win-rate threshold for the blacklist. |
| `/scanner blacklist_reset` | Clear in-memory scanner performance/blacklist data. |

The following legacy-looking commands intentionally return an unavailable
message because they have no reliable scanner execution path: `/scanner
pullback`, `/scanner adaptive`, and `/scanner ml`.

## Strategy weights (admin)

| Command | Purpose |
|---|---|
| `/weights` | Show current weights and verified performance. |
| `/weights <strategy> <weight>` | Set a strategy weight. |
| `/weights reset` | Restore default weights. |

## Configuration that must be changed outside Telegram

Set these in `.env` or the deployment configuration, then restart:

```dotenv
DEFAULT_DURATION=2
ALLOWED_TRADE_DURATIONS=2
MARTINGALE_ENABLED=false
SCANNER_DYNAMIC_TIMEFRAME=false
ML_SIGNAL_SOURCE=lstm
ML_META_GATE=shadow
ML_CONTEXT_DB=/app/data/ml/market_context.sqlite
ML_MIN_PAYOUT=0.75
ML_MIN_EXPECTED_VALUE=0.02
```

Do not expand `ALLOWED_TRADE_DURATIONS` or loosen risk gates based on raw win
rate alone. Require a broker-verified, out-of-sample sample with positive
expectancy, win rate above current payout breakeven, and a conservative
confidence bound above breakeven.
