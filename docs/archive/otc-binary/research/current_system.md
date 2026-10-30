# Current OTC System Baseline

## Purpose

This document records the Phase 0 baseline before the multi-market migration. It is descriptive, not a profitability claim, and must be updated when deployed behavior changes.

## Repository baseline

- Repository commit observed: `ffabc7e13366dfd1f7340a77f24ce3186120adee`.
- Working tree: materially dirty before Phase 0; existing modifications and untracked files are user-owned and must be preserved.
- Local Python: 3.12.13.
- Local Docker client: 29.1.3.
- Test status at audit start: `pytest` was absent from both system Python and `venv`.
- Phase 0 baseline after installing `requirements-dev.txt`: **143 passed** in 10.37 seconds using `./venv/bin/python -m pytest -q`.
- Remaining test warning: `pandas_ta` sets a pandas copy-on-write option deprecated for pandas 4.0; it does not fail the current suite but requires dependency/code review before a future pandas upgrade.

## Runtime architecture

```text
main.py
  -> OTCTradingBot
  -> APIWorker
     -> ConnectionManager
     -> MarketDataProvider
     -> OTCScanner -> StrategyEngine -> rules/ML
     -> PriorityTradeQueue
     -> AssetResolver -> IQ Option API
     -> ResultChecker -> TradeLogger/session/learning
```

Critical operational state—including active trades—is primarily in memory. The current trade history is JSON-based. Result handling attempts direct API settlement and can fall back to balance-based inference. These behaviors are not suitable as the future multi-market order-management system.

## Reusable components

- independent market harvester;
- completed-candle filtering;
- causal context feature work;
- deterministic OTC strategies and shared result objects;
- CatBoost candidate gate and directional model;
- LSTM/ONNX inference and parity concepts;
- chronological/purged research splits;
- payout-aware expectancy and calibration;
- candidate research database;
- practice-account defaults and session risk concepts;
- tests for candle completion, data-provider caching, ML strategies, scanner wiring and WebSocket locking.

## Components requiring isolation or replacement

- `APIWorker` and `OTCScanner` have excessive responsibilities.
- `AssetResolver` mixes symbol resolution and execution.
- `ResultChecker` mixes reconciliation, inference, notifications and learning.
- JSON/in-memory state is not an authoritative order ledger.
- Telegram currently exposes account switching, dry-run disabling, martingale and runtime risk mutation.
- Martingale and anti-martingale logic must not enter the future live platform.
- The vendored IQ Option client is an unofficial integration with blocking/shared-state behavior.
- Broad exception handling can hide trading invariants.

## Deployed collector observation

Read-only inspection performed 2026-08-18 against `ubuntu@152.70.46.129`:

- hostname: `otc-trading-bot`;
- process: `python3 harvest_market_data.py --mode live`;
- process start: 2026-07-31 03:49:54 UTC;
- container: Docker Compose one-off, restart policy `no`;
- primary database: `/home/ubuntu/IQoption/data/ml/market_context.sqlite`;
- observed main database size: 2,789,511,168 bytes;
- observed WAL size: 18,849,032 bytes;
- filesystem: 45 GB total, 28 GB used, 17 GB available (63% used);
- memory: 956 MiB total with swap active;
- tables: `historical_candles`, `realtime_candles`, `quote_samples`, `live_deal_events`, `deal_flow_10s`, `mood_samples`, `payout_samples`, `clock_samples`, `collection_health`, and `metadata`;
- deployment has an intended `/app/data` bind mount plus an ambiguous anonymous volume at relative `data`.

No process, container, database or live configuration was changed during inspection.

## Data and model inventory

Local data observed during Phase 0 includes:

- `data/ml/historical_candles.sqlite` — 226,095,104 bytes;
- `data/ml/market_context.sqlite` — 90,423,296 bytes in the local workspace snapshot;
- enriched Parquet and coverage report;
- CatBoost/ONNX-related training and inference scripts;
- multiple LSTM model/scaler/metadata generations.

Model hashes observed locally are recorded in `docs/research/model_artifact_hashes.sha256`. Local research-data snapshot hashes are recorded in `docs/research/data_artifact_hashes.sha256`. These identify the Phase 0 local files only; they are not a substitute for the future immutable dataset manifest.

## Research/training paths

Current scripts include candidate meta-model, directional CatBoost, CatBoost gate, regime/MTF LSTM, enriched LSTM, Kaggle candidate trainer and strategy-independent tournament programs. Their reusable logic should be consolidated later; Phase 0 does not rewrite them.

## Environment boundary

The Phase 0 migration profile is `configs/migration-safety.env.example`. It fixes the migration path to shadow/practice, disables the scanner and Telegram signals, and prohibits Telegram account switching and martingale in future platform code. It does not silently mutate the existing deployment.

## Known baseline limitations

- The green result establishes current test behavior, not complete coverage of execution, restart recovery or live broker semantics.
- Production provenance of every uncommitted local change is not yet known.
- Remote table row counts were deliberately not forced through expensive full scans while the collector was active.
- IQ Option API automation terms and jurisdiction-specific legality remain external gates.
- Existing historical model performance is not accepted as evidence until datasets, splits and artifacts are reproducibly identified.
