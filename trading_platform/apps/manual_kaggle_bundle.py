"""Prepare or validate a manual Kaggle research-data upload bundle."""

from __future__ import annotations

import argparse
from pathlib import Path

from trading_platform.research.manual_kaggle_bundle import (
    prepare_bundle_from_export,
    prepare_manual_bundle,
    validate_manual_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--dataset-id", required=True)
    inputs = prepare.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--data", action="append", type=Path)
    inputs.add_argument("--export-manifest", type=Path)
    prepare.add_argument("--output-root", type=Path, required=True)
    prepare.add_argument("--platform-root", type=Path, default=Path("trading_platform"))
    prepare.add_argument(
        "--trainer",
        type=Path,
        default=Path("trading_platform/scripts/training/train_catboost_directional.py"),
    )
    prepare.add_argument(
        "--contract",
        type=Path,
        default=Path("trading_platform/configs/research/otc_directional_v1.yaml"),
    )
    prepare.add_argument("--max-part-size-mb", type=int, default=1_000)
    validate = subparsers.add_parser("validate")
    validate.add_argument("bundle", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        if args.export_manifest:
            bundle = prepare_bundle_from_export(
                dataset_id=args.dataset_id,
                export_manifest=args.export_manifest,
                output_root=args.output_root,
                platform_root=args.platform_root,
                trainer=args.trainer,
                contract=args.contract,
                max_part_size_mb=args.max_part_size_mb,
            )
        else:
            bundle = prepare_manual_bundle(
                dataset_id=args.dataset_id,
                data_files=args.data,
                output_root=args.output_root,
                platform_root=args.platform_root,
                trainer=args.trainer,
                contract=args.contract,
            )
        print(f"Bundle ready: {bundle}")
    else:
        manifest = validate_manual_bundle(args.bundle)
        print(f"Valid bundle: {manifest['dataset_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
