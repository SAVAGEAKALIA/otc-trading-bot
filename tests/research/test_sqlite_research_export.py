import json
from pathlib import Path
import sqlite3

import pandas as pd

from trading_platform.research.sqlite_export import (
    create_consistent_snapshot,
    export_snapshot_to_parquet,
)


def collector_fixture(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO metadata VALUES ('schema_version', 'fixture-v1');
        CREATE TABLE quote_samples (
            canonical_asset TEXT NOT NULL,
            source_event_ms INTEGER NOT NULL,
            bid REAL NOT NULL,
            ask REAL NOT NULL
        );
        """
    )
    connection.executemany(
        "INSERT INTO quote_samples VALUES (?, ?, ?, ?)",
        [("EURUSD", 1_000 + index, 1.0, 1.1) for index in range(7)],
    )
    connection.commit()
    return connection


def test_online_snapshot_and_bounded_parquet_export(tmp_path) -> None:
    source = tmp_path / "live.sqlite"
    writer = collector_fixture(source)
    snapshot = create_consistent_snapshot(source, tmp_path / "snapshot.sqlite")
    writer.execute("INSERT INTO quote_samples VALUES ('EURUSD', 2000, 1.0, 1.1)")
    writer.commit()

    manifest_path = export_snapshot_to_parquet(
        snapshot, tmp_path / "export", chunk_rows=3
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parts = sorted((tmp_path / "export" / "quote_samples").glob("*.parquet"))
    exported = pd.concat([pd.read_parquet(path) for path in parts])

    assert len(parts) == 3
    assert len(exported) == 7
    assert 2_000 not in exported["source_event_ms"].tolist()
    assert manifest["collector_schema_version"] == "fixture-v1"
    writer.close()


def test_cutoff_excludes_later_rows(tmp_path) -> None:
    source = tmp_path / "live.sqlite"
    writer = collector_fixture(source)
    writer.close()
    snapshot = create_consistent_snapshot(source, tmp_path / "snapshot.sqlite")

    export_snapshot_to_parquet(
        snapshot, tmp_path / "export", chunk_rows=10, cutoff_ms=1_003
    )
    part = next((tmp_path / "export" / "quote_samples").glob("*.parquet"))

    assert pd.read_parquet(part)["source_event_ms"].max() == 1_003
