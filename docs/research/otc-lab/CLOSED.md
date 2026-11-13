# IQ Option OTC: closed (2026-11-13)

The owner closed OTC binary research on 2026-11-13. No OTC strategy is to be traded, and no OTC collection is to be started.

## Why

Every test landed at a coin flip, against a break-even of 54.35% (turbo, 0.84 payout) or 53.76% (binary, 0.86):

| Date | Study | Best result |
|---|---|---|
| 2026-10-30 | 250 live practice trades, ML | 53.2% (break-even 54.2%), log-loss equal to a coin |
| 2026-11-09 | OTC Expiry Regime, 360 fixed states | 0 of 360 qualified |
| 2026-11-11 | Quant lab: 22 model types, 10 rules, bandit, crowd fade, lead-lag | 50.94% at 1,000+ trades; REJECTED ([lab report](2026-11-11-lab-report.md)) |
| 2026-11-12 | Strict-condition research, 128 sources | no logged above-break-even result on any broker feed ([report](2026-11-12-sparse-entry-research.md)) |
| 2026-11-13 | Frozen family of 8, run once on existing data | 50.7% to 51.9%; H2, H4, H5, H8 retired ([result](2026-11-13-sparse-entry-historical-result.md)) |

Untested and abandoned: H1 and H6, the payout-step rules. They would have needed about 92 to 200 days of new collection, and nothing above suggested they would differ.

## What stays

- **Code:** `services/otc_quant_lab` and `services/otc_sparse_prereg` remain with their tests and evals, so every number above can be reproduced. `services/otc_sparse_prereg/collect.sh` must not be started; it would need the second review's minor fixes first anyway.
- **Data:** `data/ml/` (local, git-ignored) and the evidence under `docs/research/otc-lab/`.

## Reopening

Reopen only with genuinely new information that candles, mood, payout and real-FX data cannot supply, such as broker settlement records. Any new idea must be frozen in git before its outcomes are read, and certified on fresh data.
