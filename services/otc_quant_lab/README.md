# otc_quant_lab

Walk-forward research harness that asks one question: does any model, rule, regime, bandit or
adaptive policy predict IQ Option OTC binary outcomes well enough to beat the payout break-even
out of sample? Read-only over local archives. No broker connection, no orders, no credentials.

Findings and verdict: [docs/research/otc-lab/2026-11-11-lab-report.md](../../docs/research/otc-lab/2026-11-11-lab-report.md).
Sources: [docs/research/otc-lab/bibliography.md](../../docs/research/otc-lab/bibliography.md).

## Environment

The lab uses its own venv so the shared `venv/` stays untouched:

```bash
python3 -m venv .venv-lab
.venv-lab/bin/pip install numpy pandas pyarrow scipy scikit-learn lightgbm xgboost catboost pytest chronos-forecasting kaggle
.venv-lab/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
```

## Run

```bash
# gate tests (synthetic, deterministic)
.venv-lab/bin/python -m pytest services/otc_quant_lab/tests -q -p no:cacheprovider
# full study: 15 assets, 2/4/10 minute expiries, 22 model families, realtime period as second check
.venv-lab/bin/python -m services.otc_quant_lab.run_lab --out /tmp/otc-quant-lab/runs/main-120 --tf 120 --horizons 1,2,5 --models all --realtime
tail -f /tmp/otc-quant-lab/runs/main-120/progress.log
# pipeline power / false-positive controls (rubric H4/H5)
.venv-lab/bin/python -m services.otc_quant_lab.evals.eval_controls --seeds 25 --models logistic,regime_kmeans16,markov_pat3 --horizons 1,2 --out OUT
# scale-matched controls (all assets, whole archive): add --all-assets --kinds positive
# pre-registered crowd-fade test on recorded mood (Jul 31 - Aug 20 2026)
.venv-lab/bin/python -m services.otc_quant_lab.crowd
# 1 / 2 / 3 minute expiries from the recorded 1 s candles
.venv-lab/bin/python -m services.otc_quant_lab.short_expiry --out OUT/short_expiry.json
# capital and sample-size table
.venv-lab/bin/python -m services.otc_quant_lab.risk_report --out OUT/risk.json
# numbers for the report, from a finished run (v2 features: add --feature-set v2 to run_lab)
.venv-lab/bin/python -m services.otc_quant_lab.report_digest OUT/main-120 --expiry-payouts 1:0.84,2:0.84,5:0.86
# zero-shot foundation model (downloads amazon/chronos-bolt-small from Hugging Face)
.venv-lab/bin/python -m services.otc_quant_lab.foundation --sample 20000
```

The real-vs-OTC lead-lag test needs public Dukascopy ticks fetched outside the repo (never committed);
see `leadlag.py`. Dukascopy rate-limits bulk pulls (HTTP 429): fetch sequentially with backoff.

## Remote runs (Kaggle)

This WSL box is slow for the full zoo, so heavy runs go to private Kaggle CPU kernels. Every fit is cached
as `cache/<model>_h<h>_<split>.npz`, so the study shards by expiry and merges:

```bash
# one kernel per expiry: fit and cache only
python -m services.otc_quant_lab.run_lab --out OUT --horizons 1,2,5 --fit-only 2 --models all --realtime --resume \
    --bars-parquet bars_120.parquet --realtime-parquet realtime_120.parquet
# aggregation kernel: copy every shard's cache/*.npz into OUT/cache, then run without --fit-only
```

`--resume` also lets a killed local run continue. Delete `OUT/cache` after any code change that alters
features, splits or models, or stale fits are reused. Kaggle allows 5 concurrent batch CPU sessions.

Evidence is kept in `/home/saviour/otc-quant-lab-artifacts/` (not `/tmp`: a reboot wiped `/tmp` once).

## Modules

| File | Role |
|---|---|
| `data.py` | read-only loaders: archive candles, recorded realtime candles, mood, payouts |
| `features.py` | causal features (decision at bar close), currency-strength residuals, labels per expiry |
| `walkforward.py` | train / purge / inner / purge / test splits, Platt calibration, coverage thresholds, non-overlap, PBO (CSCV) |
| `metrics.py` | Wilson + Bonferroni bounds, day-block bootstrap, EV at payout, streaks, drawdown, AUC, Brier, calibration slope |
| `models.py` | 12 tabular models with one fit/predict contract |
| `seqmodels.py` | GRU, dilated TCN, CNN-LSTM, Transformer (PyTorch CPU) |
| `regimes.py` | Markov order 3/5 colour tables, K-means, GMM, forward-filtered Gaussian HMM |
| `bandit.py` | RL reduced to its exact form here: contextual bandit, greedy vs Bonferroni-LCB |
| `online.py` | prequential SGD, Page-Hinkley suspension, daily adaptive model switching |
| `baselines.py` | MHI, exhaustion, trend, mean reversion, breakout, false breakout, RSI |
| `martingale.py` | model-free tests: sign autocorrelation, variance ratio, pattern tables, hour, lead-lag |
| `crowd.py` | frozen crowd-fade band on recorded mood |
| `leadlag.py` | real interbank FX vs OTC lead-lag |
| `foundation.py` | Chronos-Bolt zero-shot |
| `risk.py` | Kelly, losing-streak probability, bankroll survival, sample size |
| `risk_report.py` | the report's capital table, with every parameter stated |
| `short_expiry.py` | 1 / 2 / 3 minute expiries labelled from 1 s candles; bar-proxy agreement |
| `report_digest.py` | deterministic extraction of every number the report quotes (C1 counts, winners, bests) |

## Data roles

The candle archive (`data/ml/historical_candles.sqlite`, Mar 29 - Jul 27 2026 at 120 s) was already
examined by earlier repo studies. It can support at most a PROMISING verdict. VALIDATED needs
prospective data recorded after a policy is frozen (fresh collector cohort or practice cash).

## Failure modes this harness guards against

- HMM decoding with forward-backward or Viterbi uses future bars; `regimes.forward_filter` is forward-only and tested.
- Thresholds, calibration and clusters are fit on train or inner days only; never on the test window.
- Unadjusted per-context LCB admits noise cells (caught by `test_bandit_lcb_abstains_on_negative_ev_and_greedy_overfits`); z is Bonferroni-adjusted.
- `TRAIN_CAP` slices the most recent rows, so train rows are passed in time order (`chrono`), not asset order.
