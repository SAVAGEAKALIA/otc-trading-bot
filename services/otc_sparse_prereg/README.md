# otc_sparse_prereg: pre-registered sparse-entry tests

> **Closed 2026-11-13.** OTC research is closed (see `docs/research/otc-lab/CLOSED.md`). Do not start `collect.sh`.

The 2026-11-12 report ([../../docs/research/otc-lab/2026-11-12-sparse-entry-research.md](../../docs/research/otc-lab/2026-11-12-sparse-entry-research.md)) asked whether IQ Option OTC can be traded only when a strict condition holds. This service turns its answer into a test that cannot be bent after the fact.

The measurable outcome is one state per hypothesis on a fresh forward block: CERTIFIED, NULL-INFORMATIVE, UNDERPOWERED or FUTILE. The default is NO TRADE. Nothing here trades. A CERTIFIED row permits only a practice-account trial, and only with the owner's go-ahead.

## What is frozen

- `spec.py` holds the family of 8 (plus H2b, nested behind H2). It records the alpha (0.05 / 8), the planning edge (+5 pt), the design effect (1.5), each hypothesis's expiry, side and horizon, and the forward start of **2026-11-14T12:00:00Z**. That start is after the server's 2026-11-07 cohort ends, so two collectors never share the account.
- `run.py freeze` writes `docs/research/otc-lab/sparse-entry/registration.json`. It contains:
  - the spec;
  - thresholds frozen on the spent archive: per-asset 99.5% / 99.9% quantiles of |z0| and the pooled 99% quantile of |mkt0|;
  - the archive's SHA-256 and range;
  - exact-rule trigger counts on the archive (counts only);
  - the collection flags;
  - SHA-256 of every source file that can change a result.

  It refuses to run once the forward block has started.
- `run.py verify` re-hashes everything. `evaluate` and `collect.sh` refuse to run when verification fails.

## Certificate (one look per hypothesis)

The look happens at the first `n_target` labeled trades (1,648 turbo, 1,653 binary), or when the hypothesis's horizon ends (60 days; 100 for H6; 210 for H1), whichever comes first. A row is CERTIFIED only if all of these hold:

1. The one-sided Clopper-Pearson lower bound at alpha 0.00625 exceeds the mean break-even of the traded payouts, with ties refunded.
2. It also does so with ties counted as losses.
3. The day-block bootstrap lower bound of mean return per stake is above 0.
4. Mean return is positive in each chronological third.

Extra conditions apply to some rows:
- **H1** must also beat its matched mood-only control (one-sided z test at 0.05).
- **H4** must also beat the 99th percentile of 1,000 placebo lattices.
- **H2b** opens only if H2 certifies.
- **H7** is never tradable, even if certified.

Before its look, a row reports counts only, never a win rate. Futility (running upper bound below break-even, n >= 100) can stop a row at any time but never certify one, so repeated looks do not inflate false positives.

## Historical test on data already collected (2026-11-13)

The owner chose not to wait months for forward data, so `historical.py` runs the frozen family once on what already exists. The plan (`docs/research/otc-lab/sparse-entry/historical/plan.json`) was committed before any outcome of these rules was read:
- **Candle rules** (H2 to H5, H8): thresholds come from the 2-min archive's first 40% of days (2026-03-29 to 05-15). Outcomes are read only for 2026-05-16 to 07-27, using a close-to-close proxy at nominal payout.
- **Event rules** (H1, H6, H7): these use the Jul 31 to Aug 20 live window, with 1-s labels and real payouts.
- **Certificate:** the same certificate and alpha as the forward block.

The evidence grade is DEVELOPMENT. A certified row earns only a short forward confirmation of that row; a non-certified row is retired.

## Data

Collection uses `collect.sh`, which wraps `trading_platform/scripts/harvest_market_data.py` with the registered flags:
- 15 pairs;
- payout every 30 s (it was 300 s);
- mood every 5 s;
- live 1-s, 2-min and 5-min candles;
- PRACTICE authentication profile, no orders.

Trigger candles for H2 to H5 and H8 come only from history-API candles (`collect.sh backfill`, run before each look with the live process stopped). That is the same API family as the archive the thresholds were frozen on. Live 1-s candles give the entry price (decision + 2 s) and the expiry price. A trade missing a price or a payout no older than 120 s is excluded and counted; exclusion never depends on the outcome.

## Commands

All commands run from the repo root.

```bash
.venv-lab/bin/python -m unittest discover -s services/otc_sparse_prereg/tests -t . -q        # gate, about 1 s
.venv-lab/bin/python -m services.otc_sparse_prereg.evals.eval_power --output /tmp/sparse-prereg/eval.json  # G2/G3, about 40 s
.venv-lab/bin/python -m services.otc_sparse_prereg.run verify
services/otc_sparse_prereg/collect.sh live      # start collection (restarts on crash)
services/otc_sparse_prereg/collect.sh status    # health line; follow with: tail -f data/forward/progress.log
services/otc_sparse_prereg/collect.sh stop && services/otc_sparse_prereg/collect.sh backfill
.venv-lab/bin/python -m services.otc_sparse_prereg.run evaluate --forward-db data/forward/sparse_forward.sqlite
```

Every `evaluate` run is appended to `docs/research/otc-lab/sparse-entry/looks.jsonl`; that file is the audit trail of looks.

## Evals (periodic, deterministic, thresholds frozen)

| Gate | Check | Threshold | Result 2026-11-13 |
|---|---|---|---|
| G2a | exact CP power for a +5 pt edge at n = 1,648 | >= 0.80 | 0.943 |
| G2b | exact CP false certification at break-even | <= 0.00625 | 0.0059 |
| G2c | full certificate power, 0.6% ties (Monte Carlo) | >= 0.80 | 0.867 |
| G2d | full certificate false certification (Monte Carlo) | <= 0.00625 + 2 SE | 0.002 |
| G3a | full pipeline on a memoryless 1-s random walk | nothing certified | pass |
| G3b | same pipeline with a planted fade after extreme moves | H2 certified | pass |

G1 (weekday replay) and G3b-Deriv (real Deriv volatility ticks as a known null) are registered in `spec.GATES` but not built yet.

## Failure modes

- **Gaps.** A PC sleep or a broker disconnect leaves gaps. They lower coverage and can push a row to UNDERPOWERED, but they cannot fake a pass. `status` flags any stream older than 5 minutes.
- **History-API candles may differ from live candles.** Thresholds and triggers both use history-API candles, which is why live candles are never used for triggers.
- **Any edit to a hashed file voids the registration.** A deliberate change before 2026-11-14T12:00Z needs `freeze --force` and a new commit. After that time it means a new, separately registered family.
