"""Validate downloaded training artifacts without installing or enabling them."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_platform.research.training_artifacts import validate_training_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Artifact directory or ZIP")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = validate_training_artifacts(args.source)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
