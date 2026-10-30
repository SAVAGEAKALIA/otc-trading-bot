# Manual Kaggle upload workflow

This workflow does not require a Kaggle API token and never uploads the live
SQLite database. It creates a consistent online snapshot, streams allowlisted
collector tables to bounded Parquet chunks, and packages those chunks.

## 1. Snapshot and export without stopping collection

```bash
PYTHONPATH=. python -m trading_platform.apps.sqlite_research_export snapshot \
  data/ml/market_context.sqlite \
  data/snapshots/market-context-YYYYMMDD.sqlite

PYTHONPATH=. python -m trading_platform.apps.sqlite_research_export export \
  data/snapshots/market-context-YYYYMMDD.sqlite \
  data/exports/market-context-YYYYMMDD \
  --chunk-rows 250000
```

The snapshot command uses SQLite's online backup API and does not modify or
pause the source database. The export uses keyset pagination, so it does not
load entire tables into memory and does not suffer progressively slower
`OFFSET` scans. Use `--cutoff-ms` when a research contract fixes an earlier UTC
cutoff. The manifest records the snapshot hash, collector schema, cutoff, row
counts and each Parquet checksum.

The raw table export is archival input, not automatically a model matrix.
Directional training requires a causal feature-building stage that produces
`enriched/enriched_candles.parquet`; candidate-gate training requires
`enriched/enriched_candidates.parquet`. Never point a trainer directly at raw
quote, mood, payout or deal partitions.

Run the platform-owned read-only builder against the consistent snapshot to
create and manifest the model-ready output:

```bash
PYTHONPATH=. python -m trading_platform.apps.build_ml_feature_dataset \
  --context-db data/snapshots/market-context-YYYYMMDD.sqlite \
  --candidate-db data/candidate_research.sqlite \
  --output-dir data/prepared/otc-YYYYMMDD-v1/enriched \
  --dataset-id otc-YYYYMMDD-v1 \
  --all-history
```

The full implementation now lives inside `trading_platform`: SQLite reads,
causal context joins, technical features, output report and prepared-dataset
manifest. The root `build_ml_feature_dataset.py` file is a compatibility command
only. The generated manifest automatically includes `enriched_candidates` when
resolved candidate data exists, hashes the exact model-ready matrices and fails
validation if they change before packaging.

## 2. Prepare the upload directory

From the future platform repository root:

```bash
PYTHONPATH=. python -m trading_platform.apps.manual_kaggle_bundle prepare \
  --dataset-id YYYYMMDD-v1 \
  --export-manifest data/prepared/otc-YYYYMMDD-v1/manifest.json \
  --output-root data/manual_uploads \
  --trainer trading_platform/scripts/training/train_catboost_directional.py \
  --contract trading_platform/configs/research/otc_directional_v1.yaml \
  --max-part-size-mb 1000
```

The command verifies every file declared by the export manifest, preserves its
table-relative path inside deterministic `otc-data-part-NNN.zip` archives and
keeps each group's uncompressed input size below the configured limit. A
single exported file larger than the limit is rejected with instructions to
rerun export using fewer `--chunk-rows`. SQLite/DB/WAL/SHM files, session files
and secret-like filenames are rejected. It also creates `platform-source.zip`
from the authoritative package, selected trainer and selected contract. The
contract template's dataset ID is resolved to the immutable bundle dataset ID;
an explicitly different ID is rejected. Do not point it at the 2.79 GB live
database. The implemented flow is:

```text
live SQLite -> consistent snapshot -> causal partitioned Parquet -> bundle
```

Only the final two objects belong in Kaggle.

## 3. Validate before and after transfer

```bash
PYTHONPATH=. python -m trading_platform.apps.manual_kaggle_bundle validate \
  data/manual_uploads/otc-YYYYMMDD-v1/UPLOAD_ME
```

Download with `rsync -avP` when possible because it resumes interrupted large
transfers. Run the same validation command against the downloaded directory.
Any missing, changed or undeclared file fails validation.

## 4. Upload manually

In Kaggle, create a private dataset and upload every item inside `UPLOAD_ME`.
Keep it private until licensing and privacy review is complete. Never add
`.env`, Telegram sessions, broker cookies, account logs or database files.

Extract `platform-source.zip` in the notebook, then set:

```bash
python /kaggle/working/kaggle_otc_training.py \
  --dataset-id YYYYMMDD-v1 \
  --contract otc_directional_v1.yaml
```

Upload `notebooks/kaggle_otc_training.py` as the notebook bootstrap. It finds
the private input regardless of Kaggle username/path, verifies the declared
platform-source checksum before importing it, safely extracts every archive,
and revalidates each extracted Parquet file. It writes
`/kaggle/working/workspace.json` with the resolved data and source roots, then
requires the bundled training contract to name the same dataset before it can
invoke the allowlisted trainer. Add `--dry-run` to write the exact resolved run
record without executing training.

Before creating the experiment directory or starting a trainer, the coordinator
checks that the selected data file is non-empty, every trainer-specific Python
module is importable, and the output filesystem has at least 512 MiB or three
times the input size free, whichever is larger. The resulting
`training_preflight_v1` report is embedded in `resolved_training_run.json`.
This is a fail-fast environment check, not proof that the dataset is
statistically valid or that a GPU runtime is correctly accelerated.

Run the bundled trainer against the validated immutable data root. Download its
model, metadata and calibration-provenance outputs together. A successful
training run is still only a research candidate; register and shadow-test its
manifest before considering practice execution.

After a successful non-dry run, the coordinator validates the artifact
directory, writes a deterministic
`/kaggle/working/output/otc-training-<experiment-id>.zip`, embeds a manifest of
every member's size and SHA-256, and validates the finished ZIP again. The final
JSON output includes the archive path and SHA-256. Failed training, invalid
provenance and dry runs do not produce a downloadable archive.

For local troubleshooting, the equivalent lower-level launcher command is:

```bash
PYTHONPATH=/kaggle/working/platform \
python -m trading_platform.research.train \
  --contract /kaggle/working/platform/configs/research/otc_directional_v1.yaml \
  --data-root /kaggle/working/dataset/data \
  --source-root /kaggle/working/platform \
  --output /kaggle/working/output \
  --environment kaggle
```

The launcher accepts only known trainers and typed options, records the exact
resolved command before execution, never invokes a shell, and cannot install or
promote the resulting model.

Validate the downloaded directory or ZIP without extracting or installing it:

```bash
PYTHONPATH=. python -m trading_platform.apps.validate_training_artifacts \
  downloads/otc-training-<run-id>.zip \
  --report downloads/otc-training-<run-id>-validation.json
```

Validation rejects unsafe archive members, secret-like files, malformed or
multiple provenance manifests, missing/checksum-mismatched artifacts and a
metadata calibration ID that does not match provenance. The report maps each
logical artifact name to its verified file and explicitly states that
installation is not allowed. Registration and shadow promotion remain separate
operator actions.

## Current limitations

- The bootstrap, clean-room extraction and downloaded-artifact validator are
  implemented. The portable launcher supports directional and candidate-gate
  CatBoost plus the stationary and regime-MTF LSTM trainers. Feature generation
  is platform-owned.
- LSTM runs require PyTorch and ONNX Runtime in the Kaggle/GCP environment. The
  launcher supplies only `TRAINING_DATA_FILE`, `TRAINING_ARTIFACT_DIR` and
  `TRAINING_DATASET_ID`; contracts cannot inject arbitrary environment variables
  or shell commands.
- The portable local/Kaggle/GCP launcher and the notebook coordinator run the
  same dependency/data/disk preflight. GPU availability and performance still
  need confirmation from the selected cloud runtime and trainer logs.
- The regime-MTF artifact has a four-input ONNX contract. It must not be loaded
  by the current single-input runtime LSTM strategy; a dedicated runtime adapter
  and parity tests remain required before shadow or live use.
- No upload is automated and no Kaggle credentials are read.
- A synthetic local clean-room integration test exercises bundle discovery,
  checksum verification, safe extraction, resolved contract identity, a real
  trainer subprocess, deterministic packaging and downloaded-ZIP validation.
  A fresh Kaggle web-session rehearsal with the real exported dataset and
  selected trainer is still required before treating the notebook workflow as
  operationally proven.
