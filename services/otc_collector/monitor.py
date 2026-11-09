"""Deterministic elapsed schedule and receipt coverage, no label-based selection."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import time
from .protocol import ASSETS, canonical, iso, utc_ms


def progress(path, now_ms=None):
    now_ms = utc_ms() if now_ms is None else now_ms
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.execute("BEGIN")
    try:
        reg = json.loads(conn.execute("SELECT record_json FROM registration WHERE singleton=1").fetchone()[0])
        start, end = reg["start_ms"], reg["end_ms"]
        horizon = min(end, max(start, now_ms))
        elapsed = horizon - start
        counts = dict(conn.execute("SELECT kind,count(*) FROM observations GROUP BY kind"))
        assets = {}
        for identity in ASSETS.values():
            times = [row[0] for row in conn.execute("SELECT available_ms FROM observations WHERE kind='quote' AND asset=? AND available_ms BETWEEN ? AND ? ORDER BY available_ms,event_id", (identity, start, horizon))]
            intervals = [right - left for left, right in zip(times, times[1:])]
            internal_gaps = [value for value in intervals if value > 5000]
            leading = (times[0] - start) if times else elapsed
            trailing = (horizon - times[-1]) if times else elapsed
            covered = sum(min(5000, value) for value in intervals)
            if times:
                covered += min(5000, horizon - times[-1])
            healthy = conn.execute("SELECT count(*) FROM observations WHERE kind='quote' AND asset=? AND clock_status='ok'", (identity,)).fetchone()[0]
            assets[identity] = {"quotes": len(times), "healthy_quotes": healthy,
                                "last_receipt_ms": times[-1] if times else None,
                                "latest_quote_age_ms": trailing if times else None,
                                "coverage_ms": covered, "coverage_fraction": covered / elapsed if elapsed else 0,
                                "internal_gap_count": len(internal_gaps),
                                "internal_missing_ms": sum(value - 5000 for value in internal_gaps),
                                "leading_missing_ms": leading, "trailing_missing_ms": max(0, trailing - 5000) if times else elapsed,
                                "max_receipt_gap_ms": max([leading, trailing, *intervals], default=elapsed),
                                "quotes_per_second": len(times) * 1000 / elapsed if elapsed else 0}
        failures = [{"code": code, "count": count} for code, count in conn.execute("SELECT code,count(*) FROM health WHERE code!='clock_sync' GROUP BY code ORDER BY code")]
        latest = [{"at_ms": at, "code": code, "details": json.loads(detail)} for at, code, detail in conn.execute("SELECT at_ms,code,detail_json FROM health ORDER BY rowid DESC LIMIT 10")]
        unclosed = conn.execute("SELECT count(*) FROM sessions s WHERE s.transition='open' AND NOT EXISTS(SELECT 1 FROM sessions c WHERE c.session_id=s.session_id AND c.transition='close')").fetchone()[0]
        return {"event_title": "Fresh OTC quote collection", "at_ms": now_ms, "at_utc": iso(now_ms),
                "registration_sha256": reg["registration_sha256"], "elapsed_ms": elapsed,
                "percent_done": 100 * elapsed / (end - start), "eta_seconds": max(0, end - now_ms) / 1000,
                "counts": counts, "assets": assets, "health_counts": failures, "latest_health": latest,
                "unclosed_sessions": unclosed, "schedule_complete": now_ms >= end}
    finally:
        conn.close()


def emit(path, status_path, now_ms=None):
    status_path = Path(status_path).resolve()
    if not status_path.is_relative_to(Path("/tmp")):
        raise ValueError("progress file must be under /tmp")
    report = progress(path, now_ms)
    line = canonical(report)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    with status_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
    print(line, flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--progress-log", required=True)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    print(f"tail -f {Path(args.progress_log).resolve()}", flush=True)
    while True:
        report = emit(args.db, args.progress_log)
        if not args.watch or report["schedule_complete"]:
            return 0
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
