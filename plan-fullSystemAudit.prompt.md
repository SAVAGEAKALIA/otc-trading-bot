## Plan: Full-System Audit — OTC Binary Options Trading Bot

**TL;DR:** This bot is a heavily over-engineered OTC binary options system with ~344 recorded trades at an estimated **~30-35% win rate** (needs ~55% to break even at 80% payout). The core architecture (Telegram→Parser→Scanner→StrategyEngine→Gatekeeper→Worker→Execution→ResultChecker→Martingale) is sound, but the signal quality pipeline is broken: 9 competing strategies with contradictory philosophies, a gatekeeper that's been bypassed/relaxed into irrelevance, and a martingale recovery loop that amplifies losses. The plan below orders the investigation from highest-impact root causes to lowest.

### Steps

1. **Fingerprint Forensics — Establish ground truth from fingerprints.json.** Parse all ~344 records to compute: overall W/L/T ratio, per-strategy win rate (`strategy_used`), per-asset win rate, per-hour win rate, per-duration win rate, score-vs-outcome correlation, and martingale series net PnL. This is the *only* empirical data that matters — everything else is theory.

2. **Strategy Engine Contradiction Audit — Investigate the 9-strategy StrategyEngine and each strategy in strategies/.** The system registers trend-following (`IndicatorStrategy`, `SqueezeBreakout`), mean-reversion (`MHI`, `CCV2`, `RubberBand`, `ApexExhaustion`), and adaptive (`Adaptive`) strategies with `weight=2.0` on experimental reversal strategies. The "voting" mode picks the *single highest-scoring* signal, not a consensus — so it's not voting at all, it's a tournament masquerading as a vote. Strategies constantly cancel each other out or one extreme outlier dominates.

3. **Gatekeeper Erosion Audit — Trace the decision path through analytics.py `SignalGatekeeper.decide()`.** The `very_relaxed` preset has a minimum score of 3.0/4.0 with confidence floor 0.15 — effectively a rubber stamp. Scanner uses `normal` mode but the gatekeeper's `decide()` now only checks `abs_score >= EXECUTION_THRESHOLD` against the *strategy engine's score*, making the original confluence/pattern/MTF logic dead code. The gatekeeper has been hollowed out into a threshold comparator.

4. **Martingale Death Spiral Audit — Trace the full cycle in martingale.py, worker.py `submit_trade()`, and result_checker.py.** With a ~35% base win rate, martingale at 2.3× multiplier across 3 steps has a ~27% probability of losing all 3 steps, producing a 1 + 2.3 + 5.29 = **8.59× loss** per blown series. The `SessionManager` consecutive-loss stop of 3 is the only thing preventing ruin, but martingale losses register *per step*, meaning a single blown series instantly triggers the session stop.

5. **Result Checker Reliability Audit — Examine `check_result_by_balance_v2` and `force_result_determination` in result_checker.py.** Balance-based result detection in multi-trade mode is inherently unreliable — concurrent trades change the balance simultaneously. The 60-second deadline with "assume loss" fallback may be misclassifying wins as losses, artificially depressing the recorded win rate.

6. **Data Pipeline Integrity — Audit data_provider.py and analytics.py `MarketAnalyzer.calculate_indicators()`.** Verify candle data format consistency (the code handles both `max/min` and `high/low` keys defensively), check for look-ahead bias in indicator calculations, and confirm the 15-second cache TTL isn't serving stale data across scan cycles.

### Further Considerations

1. **Over-engineered components to potentially remove:** `SignalReAnalyzer` (deprecated but still imported), the `RollingMemoryDB` ML probability engine (Euclidean distance on 5 indicators with 344 samples is statistically meaningless), `Alpha Hours` gatekeeper (hardcoded UTC hours with no empirical validation from *this bot's* data), `tournament` vs `voting` scan modes (both funnel to the same single-winner logic), and the `PriorityTradeQueue` (unnecessary complexity when single-mode is the safe default).

2. **Core logic worth keeping:** The modular architecture (BaseStrategy → StrategyEngine → Gatekeeper → Worker pipeline), the `SessionManager` risk controls, the fingerprint logging infrastructure (invaluable for post-mortem analysis), the `MarketDataProvider` MTF bundle abstraction, and the Telegram interface/commands system.

3. **Critical question before proceeding:** Should the audit produce (A) a *fix plan* that surgically repairs the existing system's signal quality, or (B) a *rebuild plan* that strips it to one proven strategy with proper walk-forward backtesting, or (C) a *kill recommendation* if the fingerprint forensics show the edge is fundamentally absent?

