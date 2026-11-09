# OTC research

This service builds causal features and runs one fixed logistic-regression versus CatBoost comparison. It measures prediction quality, selective price-proxy win rate, coverage and hypothetical return. It does not connect to a broker or establish an executable win rate. The August 2026 data has already been explored, so every partition is spent development or diagnostic evidence.

## Fixed experiment

The registered universe is EURUSD-OTC and GBPUSD-OTC. The target has three classes: up, down and tie. Hypothetical expiry is decision plus 120 seconds in the receiver UTC clock; the export declares the exact modeled strike and terminal rule. A quote-derived label does not become an accepted binary contract.

The feature set is one received-price lookback return, own and market mood, observed payout and receipt ages. Missing mood or lookback remains missing until training-only median imputation. Receipt ages must be integer milliseconds, at most the decision timestamp and within 5 seconds for quotes, 60 seconds for mood and 10 minutes for payout. These checks reject impossible or stale features; raw observation authenticity remains the exporter’s boundary. Source-lineage hashes are declared provenance references, while CSV bytes and every saved result are verified locally.

| Partition | UTC interval | Use |
|---|---|---|
| train | before 10 August 2026 | Fit imputation, scaling, asset encoding and classifiers |
| early | 10 to 12 August | CatBoost early stopping only |
| calibration | 12 to 14 August | One scalar temperature per model |
| policy | 14 to 16 August | Select among the three registered EV cutoffs per model |
| diagnostic_test | 16 to 21 August | Score the frozen choices; never select a winner |

Intervals are half open. A label interval reaching its partition boundary is purged across both assets. CatBoost uses depth 6, at most 400 iterations and learning rate 0.05. Logistic regression uses C=1.0. Both use seed 42. Three cutoffs per model, 0, 0.03 and 0.05, comprise the six complete policies. There is no model or cutoff sweep beyond them.

A selected win earns its recorded payout ratio; a loss loses one unit; a tie fully refunds its stake under this explicit scenario. Every selected unresolved label counts as a full loss in the worst-case mean. The selector allows one global outstanding position, orders simultaneous decisions by asset then opportunity ID and keeps every input row in the decisions CSV. It chooses a cutoff only when at least 25 selections have resolved outcomes and the policy partition’s worst-case mean is positive. Otherwise it chooses NO TRADE. None of these exploratory choices authorizes deployment.

## Run locally

From the repository root, use Python 3.12 or later. The gate suite uses only the standard library and does not fit models:

```bash
python3 -m unittest discover -s services/otc_research/tests -v
```

Install the six pinned training packages in a dedicated environment. All model artifacts must live outside any Git checkout, worktree or bare repository:

```bash
python3 -m venv /tmp/otc-training-venv
/tmp/otc-training-venv/bin/python -m pip install -r services/otc_research/training_requirements.txt
/tmp/otc-training-venv/bin/python -m services.otc_research.training \
  --input /tmp/otc-dataset/matrix.csv \
  --manifest /tmp/otc-dataset/manifest.json \
  --output /tmp/otc-comparison \
  --device CPU
```

The input must contain exactly the canonical `COLUMNS` declared in `training.py`, including all ineligible and unresolved opportunities. The manifest must declare `otc_price_proxy_training_v1`, receiver-receipt availability, the hypothetical 120-second horizon, assumed product mapping and last received quote at or before expiry. Unknown schemas, extra features, evidence mixing, hash mismatches, missing receipt ages and contradictory labels fail before fitting. Reusing a populated output directory fails instead of overwriting a run.

Success writes `report.json`, `report.md`, one decisions CSV per model, frozen policy choices, classifiers, preprocessing, feature order, calibration, `saved_inference_parity.json` and an artifact hash manifest. The trainer reloads its saved preprocessing, models and calibration, verifies probabilities within 1e-12 and demands identical decisions for every candidate before reporting success. Binary models remain outside the repository. ONNX export is deferred until there is a deployment candidate and a separate runtime-parity requirement.

Each phase prints JSON and appends the same record to the run’s `progress.log`:

```bash
tail -f /tmp/otc-comparison/progress.log
```

Percent completion measures completed named phases; it does not estimate work inside a model fit. ETA remains null until completion. An admission or training failure writes a BLOCKED report with the error and last completed phase; inspect that report before starting a new run.

## Periodic eval

Run the seeded injected-edge and null comparisons plus corrupt-data and serialization checks before shipping. The output must be a new external directory:

```bash
/tmp/otc-training-venv/bin/python -m services.otc_research.evals.eval_training \
  --output /tmp/otc-training-eval
```

The eval demands that both models detect the injected synthetic edge, retain unresolved/tied/ineligible rows, avoid broad selection on null data, preserve train-only preprocessing, reject malformed manifests and receipt ages before fitting, and reproduce saved inference. The impossible-receipt regression also reintroduces the old positive-only age guard and proves that mutant admits the input the fixed loader rejects. Synthetic success validates the software, not a market edge.

Kaggle runs use this same pinned code, canonical matrix and manifest in a private, free CPU kernel. Verify their hashes before starting and keep the raw database and credentials out of the uploaded package. Kaggle and local results must retain identical registration and input hashes. No service needs restarting for offline research.
