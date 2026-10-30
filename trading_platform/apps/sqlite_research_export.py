"""Snapshot a live collector database or export a snapshot to Parquet."""

from __future__ import annotations

import argparse
from pathlib import Path

from trading_platform.research.sqlite_export import (
    create_consistent_snapshot,
    export_snapshot_to_parquet,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot")
    snapshot.add_argument("source", type=Path)
    snapshot.add_argument("destination", type=Path)
    export = commands.add_parser("export")
    export.add_argument("snapshot", type=Path)
    export.add_argument("output", type=Path)
    export.add_argument("--chunk-rows", type=int, default=250_000)
    export.add_argument("--cutoff-ms", type=int)
    args = parser.parse_args()
    if args.command == "snapshot":
        result = create_consistent_snapshot(args.source, args.destination)
        print(f"Snapshot ready: {result}")
    else:
        result = export_snapshot_to_parquet(
            args.snapshot,
            args.output,
            chunk_rows=args.chunk_rows,
            cutoff_ms=args.cutoff_ms,
        )
        print(f"Export manifest: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
