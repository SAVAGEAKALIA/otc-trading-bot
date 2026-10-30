#!/usr/bin/env bash
# Upload the feature matrix as a PRIVATE Kaggle dataset and run the GPU kernel.
# Needs Kaggle auth (~/.kaggle/access_token or kaggle.json). Usage:
#   push.sh <path/to/otc_matrix.parquet> [workdir]
set -euo pipefail
MATRIX=$(realpath "$1")
WORK=${2:-$(mktemp -d)}
HERE=$(cd "$(dirname "$0")" && pwd)
KAGGLE=${KAGGLE:-kaggle}
USER_NAME=$($KAGGLE config view | awk '/username:/ {print $3}')
ACCELERATOR=${ACCELERATOR:-NvidiaTeslaT4}  # best free GPU (T4 x2); P100 is retired
DATASET="$USER_NAME/otc-edge-matrix"
KERNEL="$USER_NAME/otc-edge-search"

mkdir -p "$WORK/dataset" "$WORK/kernel"
cp "$MATRIX" "$WORK/dataset/otc_matrix.parquet"
cat > "$WORK/dataset/dataset-metadata.json" <<EOF
{"title": "otc-edge-matrix", "id": "$DATASET", "licenses": [{"name": "other"}], "isPrivate": true}
EOF
if $KAGGLE datasets status "$DATASET" >/dev/null 2>&1; then
  $KAGGLE datasets version -p "$WORK/dataset" -m "matrix $(sha256sum "$MATRIX" | cut -c1-12)" --dir-mode zip
else
  $KAGGLE datasets create -p "$WORK/dataset" --dir-mode zip
fi
until $KAGGLE datasets status "$DATASET" 2>/dev/null | grep -q ready; do sleep 15; done

cp "$HERE/train_edge_search.py" "$WORK/kernel/"
cat > "$WORK/kernel/kernel-metadata.json" <<EOF
{"id": "$KERNEL", "title": "otc-edge-search", "code_file": "train_edge_search.py",
 "language": "python", "kernel_type": "script", "is_private": true,
 "enable_gpu": true, "enable_internet": true,
 "dataset_sources": ["$DATASET"], "competition_sources": [], "kernel_sources": []}
EOF
$KAGGLE kernels push -p "$WORK/kernel" --accelerator "$ACCELERATOR"
echo "kernel: https://www.kaggle.com/code/$KERNEL"
echo "status: $KAGGLE kernels status $KERNEL"
echo "output: $KAGGLE kernels output $KERNEL -p <dir>"
