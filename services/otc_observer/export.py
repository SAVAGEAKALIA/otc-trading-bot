"""Export a stable SQLite archive into hash-linked receiver-clock observations.

This service exports observations only. Research owns labels and model features.
No live connection or account operation is supported.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import sqlite3
import time

from contracts.otc_v1 import Observation
from contracts.otc_v1.training_schema import ASSETS
from .normalize import normalize_rows

PRODUCT = 'turbo-option'
TABLES = {'quote': 'quote_samples', 'mood': 'mood_samples', 'payout': 'payout_samples'}
COLUMNS = {
    'quote': ('broker_asset', 'source_event_ms', 'received_at_ms', 'clock_offset_ms', 'mid'),
    'mood': ('broker_asset', 'instrument_type', 'observed_bucket_ms', 'received_at_ms', 'clock_offset_ms', 'call_fraction'),
    'payout': ('broker_asset', 'instrument_type', 'observed_bucket_ms', 'received_at_ms', 'clock_offset_ms', 'payout_fraction', 'source'),
}


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def json_write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False, sort_keys=True) + '\n')


def metadata(path):
    state = path.stat()
    return (state.st_dev, state.st_ino, state.st_size, state.st_mtime_ns, state.st_ctime_ns)


def sidecars(path):
    return [Path(str(path) + suffix) for suffix in ('-wal', '-journal') if Path(str(path) + suffix).exists()]


def read_snapshot(database: Path, output: Path):
    """Fail closed unless the main file is stable and has no active WAL/journal.

    Read data, census and schemas in one query-only transaction. Hash the source
    before and after extraction. Output is immutable and cannot overwrite a run.
    """
    database = database.resolve(strict=True)
    output = output.resolve()
    if output == database or database in output.parents:
        raise ValueError('Source archive is not an output directory')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Observation export output must be new or empty')
    if sidecars(database):
        raise ValueError('Active WAL/journal present; supply a stable SQLite backup')
    output.mkdir(parents=True, exist_ok=True)
    registration = {'schema': 'otc_receiver_observation_export_v1', 'assets': list(ASSETS),
                    'product': PRODUCT, 'clock_limit_ms': 15000,
                    'quote_product_mapping': 'explicit_assumed', 'clock': 'receiver_utc',
                    'source_time_basis': 'original source/bucket retained only in lineage',
                    'available_time_basis': 'recorded received_at_ms', 'promotable': False}
    registration['code_sha256'] = {'export': sha256(Path(__file__)),
                                   'normalize': sha256(Path(__file__).with_name('normalize.py'))}
    json_write(output / 'registration.json', registration)
    def emit_early(phase):
        line = json.dumps({'event': 'OTC observation export', 'phase': phase,
                           'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                           'percent': None, 'eta_seconds': None}, sort_keys=True)
        print(line, flush=True)
        with (output / 'progress.log').open('a') as stream:
            stream.write(line + '\n')
    emit_early('hashing_source_before_extraction')
    start_state = metadata(database)
    before_hash = sha256(database)
    if metadata(database) != start_state or sidecars(database):
        raise ValueError('Source changed during initial hashing')
    con = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    con.execute('BEGIN')
    emit_early('scope_census')
    inventories = {}; counts = {}; bounds = {}; completed = 0
    with (output / 'observations.jsonl').open('w') as events_stream, (output / 'source_lineage.jsonl').open('w') as lineage_stream, (output / 'progress.log').open('a') as progress:
        def emit(event, **values):
            item = {'event': 'OTC observation export', 'phase': event,
                    'timestamp_utc': datetime.now(timezone.utc).isoformat(), **values}
            line = json.dumps(item, sort_keys=True, allow_nan=False)
            print(line, flush=True); progress.write(line + '\n'); progress.flush()
        try:
            # Census uses this same transaction; no future-derived asset universe.
            total = 0
            for kind, table in TABLES.items():
                cols = [r['name'] for r in con.execute('PRAGMA table_info(' + table + ')')]
                if not set(COLUMNS[kind]) <= set(cols):
                    raise ValueError(f'{table}: missing registered input fields')
                where = 'broker_asset IN (?,?)' + ('' if kind == 'quote' else ' AND instrument_type=?')
                parameters = (*ASSETS,) if kind == 'quote' else (*ASSETS, PRODUCT)
                census = con.execute(f'SELECT COUNT(*) AS n, MIN(received_at_ms) AS first, MAX(received_at_ms) AS last FROM {table} WHERE {where}', parameters).fetchone()
                inventories[table] = {'columns': cols, 'rows_in_scope': census['n']}
                bounds[kind] = {'first_receipt_ms': census['first'], 'last_receipt_ms': census['last']}
                total += census['n']
            emit('reading', rows_processed=0, rows_total=total, percent=0.0, eta_seconds=None)
            began = time.monotonic(); last_report = began
            for kind, table in TABLES.items():
                counter = Counter()
                where = 'broker_asset IN (?,?)' + ('' if kind == 'quote' else ' AND instrument_type=?')
                parameters = (*ASSETS,) if kind == 'quote' else (*ASSETS, PRODUCT)
                order = 'broker_asset,received_at_ms' if kind != 'payout' else 'broker_asset,source,received_at_ms'
                selected = ','.join(COLUMNS[kind])
                cursor = con.execute(f'SELECT {selected} FROM {table} WHERE {where} ORDER BY {order}', parameters)
                key = (lambda row: (row['broker_asset'], row['received_at_ms'])) if kind != 'payout' else (lambda row: (row['broker_asset'], row['source'], row['received_at_ms']))
                for _key, batch in itertools.groupby(cursor, key=key):
                    raw = [dict(row) for row in batch]
                    normalized, stats, lineage = normalize_rows(raw, kind, product=PRODUCT, assets=ASSETS)
                    counter.update(stats); completed += len(raw)
                    for item in normalized:
                        Observation(**item)
                        events_stream.write(json.dumps(item, sort_keys=True, allow_nan=False) + '\n')
                        lineage_stream.write(json.dumps({'event_id': item['event_id'], **lineage[item['event_id']]}, sort_keys=True, allow_nan=False) + '\n')
                    now = time.monotonic()
                    if now - last_report >= 15:
                        rate = completed / (now - began)
                        emit('reading', rows_processed=completed, rows_total=total, percent=round(100 * completed / total, 2), rows_per_second=round(rate, 2), eta_seconds=round((total - completed) / rate, 2))
                        last_report = now
                counts[kind] = dict(sorted(counter.items()))
                emit('table_complete', table=table, rows_processed=completed, rows_total=total, percent=round(100 * completed / total, 2), eta_seconds=None)
        finally:
            con.rollback(); con.close()
        emit('hashing_source_after_extraction', percent=None, eta_seconds=None)
        if sidecars(database) or metadata(database) != start_state or sha256(database) != before_hash or metadata(database) != start_state:
            json_write(output / 'status.json', {'status': 'BLOCKED', 'reason': 'Source changed during extraction', 'promotable': False})
            raise ValueError('Source changed during extraction; observations are not admitted')
        events_stream.flush(); lineage_stream.flush()
        manifest = {**registration, 'status': 'DONE', 'source_sha256': before_hash,
                    'source_bytes': start_state[2], 'source_id': database.name,
                    'source_stable': True, 'snapshot_basis': 'one read transaction, unchanged main file hash, no WAL/journal',
                    'inventory': inventories, 'receipt_bounds': bounds, 'normalization_counts': counts,
                    'observations_sha256': sha256(output / 'observations.jsonl'),
                    'source_lineage_sha256': sha256(output / 'source_lineage.jsonl')}
        snapshot_manifest = database.with_suffix(database.suffix + '.manifest.json')
        if snapshot_manifest.is_file():
            manifest['sqlite_snapshot_manifest_sha256'] = sha256(snapshot_manifest)
            manifest['sqlite_snapshot_basis'] = 'consistent online backup; original source identity recorded in adjacent snapshot manifest'
        json_write(output / 'manifest.json', manifest)
        emit('complete', rows_processed=completed, rows_total=total, percent=100.0, eta_seconds=0, output_rows=sum(item.get('output', 0) for item in counts.values()))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    read_snapshot(args.database, args.output)


if __name__ == '__main__':
    main()
