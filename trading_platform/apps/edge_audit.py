"""Check candle rules or a settled trade log against binary-option breakeven.

Examples:
    python -m trading_platform.apps.edge_audit --candles data/ml/mtf_candles.parquet
    python -m trading_platform.apps.edge_audit --trade-log data/trade_log.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from trading_platform.research.validation.edge_audit import (
    audit_candle_rules,
    audit_trade_log,
    direction_frame,
    render_json,
    render_markdown,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--candles", type=Path, help="Parquet with asset, timeframe, timestamp, open, close")
    source.add_argument("--trade-log", type=Path, help="JSON list of settled trades (trade_log.json)")
    parser.add_argument("--payout", type=float, default=0.85, help="Win payout fraction (default 0.85)")
    parser.add_argument("--timeframe", type=int, action="append", help="Seconds; repeat to select several")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)

    if args.trade_log:
        result = audit_trade_log(json.loads(args.trade_log.read_text()), args.payout)
        print(render_json([result]) if args.format == "json" else render_markdown("Settled trades", [result]))
        return 0

    candles = pd.read_parquet(args.candles, columns=["asset", "timeframe", "timestamp", "open", "close"])
    for timeframe in args.timeframe or sorted(candles["timeframe"].unique()):
        frame = direction_frame(candles[candles["timeframe"] == timeframe], int(timeframe))
        results = audit_candle_rules(frame, args.payout)
        title = f"{int(timeframe)}s candles ({len(frame):,} samples)"
        print(render_json(results) if args.format == "json" else render_markdown(title, results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
