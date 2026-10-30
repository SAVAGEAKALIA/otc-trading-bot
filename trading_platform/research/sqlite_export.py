"""Consistent SQLite snapshots and bounded-memory research exports."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3

import pandas as pd

from trading_platform.research.training_provenance import sha256_file


RESEARCH_TABLE_TIMES = {
    "historical_candles": "candle_start_ms",
    "realtime_candles": "candle_start_ms",
    "quote_samples": "source_event_ms",
    "mood_samples": "observed_bucket_ms",
    "payout_samples": "observed_bucket_ms",
    "live_deal_events": "COALESCE(event_time_ms, received_at_ms)",
    "clock_samples": "observed_bucket_ms",
    "collection_health": "observed_bucket_ms",
}


def validate_research_export(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") not in {
        "sqlite_research_export_v1",
        "prepared_research_dataset_v1",
    }:
        raise ValueError("unsupported research export schema")
    root = manifest_path.parent
    declared = set()
    for record in manifest.get("records", []):
        if "path" not in record:
            continue
        relative = Path(str(record["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("research export contains an unsafe path")
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"research export file is missing: {relative}")
        if path.stat().st_size != int(record["size"]):
            raise ValueError(f"research export size mismatch: {relative}")
        if sha256_file(path) != record["sha256"]:
            raise ValueError(f"research export checksum mismatch: {relative}")
        declared.add(relative.as_posix())
    if not declared:
        raise ValueError("research export contains no data files")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and (path.name.endswith(".parquet") or path.name.endswith(".csv.gz"))
    }
    if actual != declared:
        raise ValueError("research export contains undeclared or missing Parquet files")
    return manifest


def open_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(
        f"file:{path.resolve()}?mode=ro", uri=True, timeout=30.0
    )
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def create_consistent_snapshot(source: Path, destination: Path) -> Path:
    """Use SQLite's online backup API without pausing the writer."""

    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = open_read_only(source)
    target_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(target_connection, pages=2_048, sleep=0.05)
        result = target_connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"snapshot integrity check failed: {result}")
    except Exception:
        target_connection.close()
        source_connection.close()
        if destination.exists():
            destination.unlink()
        raise
    target_connection.close()
    source_connection.close()
    return destination


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{table}")')
    ]


def export_snapshot_to_parquet(
    snapshot: Path,
    output: Path,
    *,
    chunk_rows: int = 250_000,
    cutoff_ms: int | None = None,
) -> Path:
    if chunk_rows <= 0:
        raise ValueError("chunk_rows must be positive")
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    connection = open_read_only(snapshot)
    records = []
    try:
        existing = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for table, time_expression in RESEARCH_TABLE_TIMES.items():
            if table not in existing:
                continue
            columns = _table_columns(connection, table)
            if not columns:
                continue
            table_dir = output / table
            table_dir.mkdir()
            last_time = -1
            last_rowid = -1
            part = 0
            total_rows = 0
            maximum_time = None
            cutoff_clause = f"AND {time_expression} <= ?" if cutoff_ms is not None else ""
            while True:
                parameters = [last_time, last_time, last_rowid]
                if cutoff_ms is not None:
                    parameters.append(cutoff_ms)
                parameters.append(chunk_rows)
                query = f"""
                    SELECT rowid AS __rowid__, * , {time_expression} AS __event_time__
                    FROM "{table}"
                    WHERE ({time_expression} > ? OR
                          ({time_expression} = ? AND rowid > ?))
                    {cutoff_clause}
                    ORDER BY {time_expression}, rowid
                    LIMIT ?
                """
                frame = pd.read_sql_query(query, connection, params=parameters)
                if frame.empty:
                    break
                last_time = int(frame["__event_time__"].iloc[-1])
                last_rowid = int(frame["__rowid__"].iloc[-1])
                maximum_time = last_time
                frame = frame[columns]
                part += 1
                target = table_dir / f"part-{part:05d}.parquet"
                frame.to_parquet(target, index=False)
                total_rows += len(frame)
                records.append(
                    {
                        "table": table,
                        "path": target.relative_to(output).as_posix(),
                        "rows": len(frame),
                        "size": target.stat().st_size,
                        "sha256": sha256_file(target),
                    }
                )
            if total_rows == 0:
                table_dir.rmdir()
            else:
                records.append(
                    {
                        "table_summary": table,
                        "rows": total_rows,
                        "parts": part,
                        "maximum_event_time_ms": maximum_time,
                    }
                )
        schema_version_row = connection.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone() if "metadata" in existing else None
    finally:
        connection.close()
    manifest = {
        "schema_version": "sqlite_research_export_v1",
        "source_snapshot_sha256": sha256_file(snapshot),
        "collector_schema_version": schema_version_row[0] if schema_version_row else None,
        "cutoff_ms": cutoff_ms,
        "created_at": datetime.now(UTC).isoformat(),
        "records": records,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    validate_research_export(manifest_path)
    return manifest_path
