# Enriched LSTM and CatBoost pipeline

This pipeline now has an immediate directional CatBoost option and a later
candidate-filter role:

```text
closed broker candles + causal market context
                    |
                    v
 LSTM, directional CatBoost, or conventional strategy
             proposes CALL/PUT
                    |
                    v
       CatBoost estimates candidate win
                    |
                    v
     payout + expected-value acceptance gate
```

The two CatBoost artifacts are deliberately separate. Directional CatBoost
chooses CALL/PUT from enriched candles. The CatBoost meta-gate never chooses or
reverses direction; its positive class is “the supplied candidate wins.”

For the immediate candle-model workflow, see
[`directional-catboost-training.md`](directional-catboost-training.md).

## 1. Collect the two required ledgers

Keep the read-only harvester running to populate
`data/ml/market_context.sqlite`. Keep the bot scanner running in practice or
dry-run mode so `data/candidate_research.sqlite` records every strategy
candidate before downstream scanner filters and later resolves it from exact
broker candle boundaries.

```bash
python3 harvest_market_data.py \
  --mode live \
  --mood-interval-seconds 5 \
  --payout-interval-seconds 300 \
  --live-timeframes 1,120,300,900
```

Useful Telegram setup while collecting candidates:

```text
/dryrun on
/martingale off
/scanner mlgate shadow
/scanner on
/scanner research
```

The harvester database is opened read-only by both the dataset builder and the
live bot. The builder does not stop, lock for writing, or modify the collector.

## 2. Build causally joined datasets

```bash
PYTHONPATH=. python -m trading_platform.apps.build_ml_feature_dataset \
  --context-db data/ml/market_context.sqlite \
  --candidate-db data/candidate_research.sqlite \
  --output-dir data/ml/enriched
```

Outputs:

- `enriched_candles.parquet`: input to the LSTM trainer;
- `enriched_candidates.parquet`: input to the CatBoost trainer, created once
  resolved candidates exist;
- `coverage_report.json`: feed coverage, date span, and missing rates.

Every context query is bounded by `feature_time <= decision_time`. Quote,
mood, payout, and public-deal values that exceed their freshness limit receive
an explicit missing flag. No nearest/future join and no backfill is used.

## 3. Train CatBoost on Kaggle

This section trains the later candidate gate. For the immediate directional
model that consumes `enriched_candles.parquet`, use
`trading_platform/scripts/training/train_catboost_directional.py` as documented above.

Upload `train_catboost_gate.py`, the complete `trading_platform/` package
tree, and `enriched_candidates.parquet`. Preserve the package beneath a
top-level `trading_platform/` directory. The root `training_provenance.py` file is only a
temporary compatibility shim; new training code must import the platform
package. Then run:

```bash
python -m pip install catboost==1.2.10 scikit-learn==1.9.0 \
  pandas==2.3.3 numpy==2.2.6 joblib pyarrow pandas-ta==0.4.71b0

export PYTHONPATH=/kaggle/working/src

python train_catboost_gate.py \
  --data /kaggle/input/YOUR_DATASET/enriched_candidates.parquet \
  --dataset-id otc-enriched-candidates-YYYYMMDD-v1 \
  --output-dir /kaggle/working/catboost_gate \
  --gpu
```

The trainer requires 2,000 resolved candidates and 70% coverage for quote,
mood, and payout context by default. It reports the available calendar span
but does not block training merely because it is shorter than 30 days. Use the
optional `--minimum-days N` argument only when you deliberately want that
pre-training restriction. It uses separate train, early-stop, calibration,
threshold-policy,
and untouched-test periods. Threshold selection uses actual decision-time
payouts and a daily-block bootstrap. It writes:

```text
catboost_gate.cbm
catboost_calibrator.joblib
catboost_gate_metadata.json
catboost_gate_calibration_provenance.json
catboost_policy_thresholds.csv
```

The trainer hashes the source dataset before training, verifies it did not
change, hashes the final model/calibrator, and writes the strict registration
manifest. Download that manifest with the artifacts. The generated
`calibration_id` is also embedded in `catboost_gate_metadata.json`.

Do not enforce the model unless `offline_deployment_approved` is `true` in the
metadata. The live gate independently checks the model, calibrator, metadata,
feature order, positive-class definition, and context schema.

## 4. Train the enriched LSTM on Kaggle

Upload `trading_platform/scripts/training/train_trading_model_v3.py`, `requirements-training.txt`, and
`enriched_candles.parquet`:

```bash
python -m pip install -r requirements-training.txt

TRAINING_DATA_FILE=/kaggle/input/YOUR_DATASET/enriched_candles.parquet \
TRAINING_ARTIFACT_DIR=/kaggle/working/lstm_enriched \
python trading_platform/scripts/training/train_trading_model_v3.py
```

The epoch loop still runs and uses early stopping. The model input includes
stationary candle features, quote spread/freshness, trailing public-deal flow,
traders’ mood, payout/breakeven, explicit missing flags, and optional asset
identity. The supervised label is the next exact two-minute candle direction
from its open to its close.

Deploy the LSTM artifacts only when `deployment_approved` is true:

```text
deep_lstm_v1.onnx
lstm_scaler.pkl
lstm_metadata.pkl
```

## 5. Install artifacts and validate in practice

Copy one complete run of each model into `data/ml/models/`. Never mix a model,
calibrator/scaler, and metadata from different runs.

```bash
mkdir -p data/ml/models
cp /path/to/lstm_enriched/deep_lstm_v1.onnx data/ml/models/
cp /path/to/lstm_enriched/lstm_scaler.pkl data/ml/models/
cp /path/to/lstm_enriched/lstm_metadata.pkl data/ml/models/
cp /path/to/catboost_gate/catboost_gate.cbm data/ml/models/
cp /path/to/catboost_gate/catboost_calibrator.joblib data/ml/models/
cp /path/to/catboost_gate/catboost_gate_metadata.json data/ml/models/

docker compose up -d --build
docker compose logs -f --tail=150 otc-bot
```

Start with shadow decisions:

```text
/account
/dryrun on
/martingale off
/scanner mlsignal lstm
/scanner mlgate shadow
/scanner mlpayout 75
/scanner mledge 2
/scanner status
/scanner on
```

After a sufficiently large broker-verified forward cohort agrees with the
untouched test and the CatBoost metadata is approved:

```text
/scanner mlgate enforce
/scanner status
```

`enforce` is fail-closed: missing/stale quote, mood, or payout context; an
unavailable artifact; an unapproved artifact; low payout; low calibrated
candidate probability; or insufficient expected value all reject the trade.

## 6. Safe rollback

The model components are independently removable at runtime:

```text
/scanner mlgate off
/scanner mlsignal off
```

Turning off CatBoost restores the strategy engine’s normal path. Turning off
the LSTM removes only the ML directional strategy; conventional strategies
remain available. The running harvester is independent of both settings.
