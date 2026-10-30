#!/usr/bin/env bash
# Run the round-2 family tournament on Kaggle (T4 x2) against a private dataset.
# The kernel file is train_edge_search.py (minus its __main__ block) followed by
# family_tournament.py (minus its __future__ import), so shared code is not duplicated.
# Usage: push_tournament.sh <dataset-slug> [workdir]   e.g. saviourakalia/otc-edge-matrix-r2
set -euo pipefail
DATASET=$1
WORK=${2:-$(mktemp -d)}
HERE=$(cd "$(dirname "$0")" && pwd)
KAGGLE=${KAGGLE:-kaggle}
USER_NAME=$($KAGGLE config view | awk '/username:/ {print $3}')
KERNEL="$USER_NAME/otc-family-tournament"
mkdir -p "$WORK"
python3 "$HERE/build_tournament_kernel.py" "$HERE" "$WORK/family_tournament_kernel.py"
cat > "$WORK/kernel-metadata.json" <<META
{"id": "$KERNEL", "title": "otc-family-tournament", "code_file": "family_tournament_kernel.py",
 "language": "python", "kernel_type": "script", "is_private": true,
 "enable_gpu": true, "enable_internet": true,
 "dataset_sources": ["$DATASET"], "competition_sources": [], "kernel_sources": []}
META
$KAGGLE kernels push -p "$WORK" --accelerator "${ACCELERATOR:-NvidiaTeslaT4}"
echo "kernel: https://www.kaggle.com/code/$KERNEL"
