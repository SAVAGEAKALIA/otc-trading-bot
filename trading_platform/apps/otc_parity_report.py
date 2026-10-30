"""Generate a read-only OTC shadow parity report from the platform ledger."""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import create_engine

from trading_platform.storage.repository import LedgerRepository
from trading_platform.strategies.otc.reporting import build_otc_parity_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database_url", help="SQLAlchemy URL for the shadow ledger")
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write to file instead of stdout")
    args = parser.parse_args()
    engine = create_engine(args.database_url, pool_pre_ping=True)
    try:
        report = build_otc_parity_report(
            LedgerRepository(engine).list_signal_decisions()
        )
        rendered = report.to_json() if args.format == "json" else report.to_markdown()
    finally:
        engine.dispose()
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
