# Directional CatBoost training

Directional CatBoost is the immediate model trained from
`enriched_candles.parquet`. It predicts whether the next exact two-minute
candle will close above or below its own open. It is separate from the later
CatBoost candidate gate, which uses `enriched_candidates.parquet` to accept or
reject a direction proposed by another strategy.

## Build the candle dataset

From the project root:

```bash
PYTHONPATH=. python -m trading_platform.apps.build_ml_feature_dataset \
  --context-db data/ml/market_context.sqlite \
  --candidate-db data/candidate_research.sqlite \
  --output-dir data/ml/enriched
```

The candidate database may be empty. Directional training needs only
`enriched_candles.parquet` (or the `.csv.gz` fallback).

## Train on Kaggle

Upload `trading_platform/scripts/training/train_catboost_directional.py`, the complete `trading_platform/`
package tree, and the enriched candle file. Preserve the package beneath a
top-level `trading_platform/` directory; `training_provenance.py` at the repository root is
only a temporary local compatibility shim and is not the authoritative
implementation. Install dependencies in a Python 3.12 notebook:

```bash
python -m pip install \
  catboost==1.2.10 pandas==2.3.3 numpy==2.2.6 \
  pandas-ta==0.4.71b0 scikit-learn==1.9.0 joblib pyarrow
```

Set the package path before invoking the transitional root trainer:

```bash
export PYTHONPATH=/kaggle/working
```

The script automatically discovers `enriched_candles.parquet` recursively
under `/kaggle/input`, or accepts an explicit path:

```bash
python trading_platform/scripts/training/train_catboost_directional.py \
  --data /kaggle/input/YOUR_DATASET/enriched_candles.parquet \
  --dataset-id otc-enriched-candles-YYYYMMDD-v1 \
  --output-dir /kaggle/working/catboost_directional \
  --gpu
```

There is no 30-day pre-training block. Short history produces a warning and
continues. The default minimum is 500 usable labeled rows; lowering it is
possible with `--minimum-rows`, but that does not relax final approval rules.

The trainer uses separate chronological train, early-stop, probability
calibration, threshold-policy, and untouched-test periods. The confidence
threshold is selected for payout-aware expectancy after applying a five-minute
per-asset opportunity cooldown.

Required runtime artifacts:

```text
catboost_directional.cbm
catboost_directional_calibrator.joblib
catboost_directional_metadata.json
catboost_directional_calibration_provenance.json
```

`catboost_directional_thresholds.csv` is a research report and is not required
by the live bot.

The provenance manifest contains the immutable dataset ID/hash, chronological
split boundaries, final-test probability metrics, deployment-gate result, and
SHA-256 hashes of the exact model and calibrator. Its `calibration_id` is also
written into the normal metadata. Download the manifest with the artifacts;
do not edit it after training.

## Practice deployment

Copy one complete run together:

```bash
mkdir -p data/ml/models
cp /path/to/catboost_directional/catboost_directional.cbm data/ml/models/
cp /path/to/catboost_directional/catboost_directional_calibrator.joblib data/ml/models/
cp /path/to/catboost_directional/catboost_directional_metadata.json data/ml/models/
cp /path/to/catboost_directional/catboost_directional_calibration_provenance.json data/ml/models/
docker-compose up -d --build
docker-compose logs -f --tail=150
```

Run an isolated research cohort:

```text
/scanner off
/telegram off
/dryrun on
/martingale off
/scanner mlsignal catboost
/scanner strategy ml_catboost
/scanner scan_mode tournament
/scanner agreement 1
/scanner families 1
/scanner regime off
/scanner mlbypass on
/scanner mlgate shadow
/scanner mlpayout 75
/scanner mledge 2
/scanner on
/scanner status
```

An artifact that failed its offline gate is marked `research-only` in status
and signal warnings. Keep such a run in dry-run or PRACTICE mode. Fresh quote,
mood, and payout context is still required at inference time.

## Later candidate-gate promotion

Keep `CANDIDATE_RESEARCH_ENABLED=true` while directional CatBoost runs. The bot
will record its proposed directions and resolve their broker-candle outcomes.
When `enriched_candidates.parquet` becomes sufficiently large, train
`train_catboost_gate.py` and install its separate artifacts.

Then enable filtering without changing the directional model:

```text
/scanner mlsignal catboost
/scanner strategy ml_catboost
/scanner mlgate enforce
```

The directional model continues to choose CALL or PUT; the candidate gate can
only accept or reject that proposal.
