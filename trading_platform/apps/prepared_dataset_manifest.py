"""Create a checksum manifest for model-ready causal research files."""

from __future__ import annotations

import argparse
from pathlib import Path

from trading_platform.research.prepared_dataset import create_prepared_dataset_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--file",
        action="append",
        required=True,
        metavar="ROLE=PATH",
    )
    args = parser.parse_args()
    files = {}
    for value in args.file:
        role, separator, path = value.partition("=")
        if not separator or not role or not path:
            raise ValueError("--file must use ROLE=PATH")
        if role in files:
            raise ValueError(f"duplicate dataset role: {role}")
        files[role] = Path(path)
    result = create_prepared_dataset_manifest(
        dataset_id=args.dataset_id,
        root=args.root,
        files=files,
    )
    print(f"Prepared dataset manifest: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
