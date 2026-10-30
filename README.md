# Trading platform

**Status (2026-10-30):** transition from IQ Option OTC binaries to crypto.

- The OTC binary bot was measured with **no tradeable edge** across three research
  rounds. That covered 32 strategies, from rules to CatBoost, LightGBM, XGBoost,
  GRU, TCN and transformers, plus crowd follow/fade. Evidence:
  [docs/plans/2026-10-30-direction-reset.md](docs/plans/2026-10-30-direction-reset.md).
- The binary bot is archived, not deleted:
  - git tag `otc-binary-final-2026-10-30`
  - branch `archive/otc-binary`
  - OTC docs in `docs/archive/otc-binary/`
  - research artifacts and server exports in `data/archive/otc-binary-2026-10-30/`
    (local only, checksummed)
- The crypto plan is in `docs/plans/` and is awaiting approval.

## What is here now

| Path | What |
|---|---|
| `trading_platform/domain` | Immutable domain contracts (instruments, orders, fills, decisions) |
| `trading_platform/execution`, `risk`, `storage` | OMS reconciliation, deterministic risk engine, order ledger/outbox |
| `trading_platform/brokers/bybit`, `simulated`, `weex` | Exchange adapters and a simulated broker |
| `trading_platform/research` | Backtests, purged walk-forward, `edge_audit` breakeven gate, trial registry, crypto baselines |
| `trading_platform/interfaces` | Telegram operator console |

## Checks

```bash
venv/bin/python -m pytest -q
python -m trading_platform.apps.edge_audit --help
```

## Restore the binary bot

```bash
git checkout otc-binary-final-2026-10-30
```
