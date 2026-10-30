# LSTM v4 cloud training

The standalone trainer is `trading_platform/scripts/training/train_trading_model_v3.py`; its implementation and
artifacts are versioned as `stationary_probability_v4`. The older filename is
kept so existing cloud notebook upload steps do not break.

## Input

First run the platform-owned feature builder beside a consistent harvester
snapshot.
Upload these files to the cloud runtime:

- `trading_platform/scripts/training/train_trading_model_v3.py`
- `requirements-training.txt`
- `enriched_candles.parquet`

The Parquet file contains broker candles plus causally joined quote, mood,
payout, and public-deal-flow fields. It is produced with:

```bash
PYTHONPATH=. python -m trading_platform.apps.build_ml_feature_dataset \
  --context-db data/ml/market_context.sqlite \
  --candidate-db data/candidate_research.sqlite \
  --output-dir data/ml/enriched
```

Only complete 120-second rows are used. A history shorter than 30 UTC days
produces a warning but does not prevent training. Quote, mood, and payout
coverage must each be at least 70%. Missing public-deal events are retained
with a missing flag rather than fabricated as neutral volume.

## Environment

Use Python 3.12. Do not replace a cloud runtime's working CUDA-enabled PyTorch
installation just to satisfy the requirements file.

```bash
python3 -m pip install \
  numpy==2.2.6 pandas==2.3.3 pandas-ta==0.4.71b0 \
  scikit-learn==1.9.0 "joblib>=1.5,<2" \
  "pyarrow>=19,<22" "onnx>=1.17,<2" "onnxruntime>=1.20,<2"
```

Install PyTorch only when the runtime does not already provide it, following
the wheel command appropriate for that runtime's CUDA version.

## Train

```bash
TRAINING_DATA_FILE=enriched_candles.parquet \
TRAINING_ARTIFACT_DIR=lstm_stationary_v4_artifacts \
python3 trading_platform/scripts/training/train_trading_model_v3.py
```

The epoch loop still runs with early stopping. The script uses:

1. training rows for weights and scaler fitting;
2. an early-stop partition for epoch selection;
3. the first chronological half of calibration for temperature scaling;
4. the second chronological half for confidence-threshold selection;
5. an untouched final test partition exactly once.

The minimum candidate threshold is 65%. It is not automatically approved:
the selected threshold must retain enough trades and independent days, beat
the payout breakeven rate conservatively, and beat a null probability model
on Brier score and log loss.

## Required outputs

Do not deploy an incomplete artifact set:

```text
deep_lstm_v1.onnx
lstm_scaler.pkl
lstm_metadata.pkl
lstm_metadata.json
calibration_thresholds.csv
calibration_reliability.csv
test_reliability.csv
test_per_asset_metrics.csv
training_history.csv
split_calendar.csv
```

Inspect `lstm_metadata.json`. Continue only when all are true:

```json
{
  "threshold_selection_passed": true,
  "onnx_verification_passed": true,
  "deployment_approved": true
}
```

A failed deployment gate is a valid research result. Lowering the confidence
threshold until the gate passes would invalidate the experiment.

## Practice deployment

Back up the current three runtime artifacts, then copy the new ONNX, scaler,
and pickle metadata together into `data/ml/models/`. Never mix files from two
training runs.

Rebuild the container, confirm that the log reports the v4 feature count and
artifact threshold, then use only the isolated practice scanner cohort:

```text
/telegram off
/martingale off
/scanner off
/scanner strategy ml_lstm
/scanner mlsignal lstm
/scanner mlgate shadow
/scanner scan_mode tournament
/scanner agreement 1
/scanner families 1
/scanner timeframe 2
/scanner mlbypass on
/scanner on
/scanner status
```

Do not override the artifact threshold initially. Use `/breakdown` and
`/scanner research` to compare live broker-verified results with the untouched
test report.

Keep CatBoost in `shadow` while establishing the live candidate cohort. Change
it to `enforce` only after its own untouched-test metadata is approved.
