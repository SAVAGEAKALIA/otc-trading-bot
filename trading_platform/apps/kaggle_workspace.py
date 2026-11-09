"""Discover, validate and extract an uploaded manual Kaggle bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_platform.research.kaggle_workspace import (
    discover_bundle,
    prepare_kaggle_workspace,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=Path("/kaggle/input"))
    parser.add_argument("--working-root", type=Path, default=Path("/kaggle/working"))
    parser.add_argument("--dataset-id")
    args = parser.parse_args()
    bundle = discover_bundle(args.input_root, args.dataset_id)
    result = prepare_kaggle_workspace(bundle=bundle, working_root=args.working_root)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
