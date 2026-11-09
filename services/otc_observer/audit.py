"""Read-only provenance audit of archived OTC SQLite observations."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time

TABLES = ('quote_samples', 'mood_samples', 'payout_samples', 'realtime_candles', 'historical_candles', 'live_deal_events', 'candidates', 'candidate_signals', 'candidate_outcomes')
TIMES = ('source_event_ms', 'received_at_ms', 'server_at_receive_ms', 'observed_bucket_ms', 'candle_start_ms')


def identifier(name):
    return '"' + name.replace('"', '""') + '"'


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(part)
    return digest.hexdigest()


def inspect_database(path: Path, *, clock_limit_ms=15_000, hash_input=True):
    if clock_limit_ms < 0:
        raise ValueError('Clock limit must be nonnegative')
    path = path.resolve(strict=True)
    before = path.stat()
    result = {'path': str(path), 'size_bytes': before.st_size, 'clock_limit_ms': clock_limit_ms,
              'tables': {}, 'read_only': True, 'source_sha256': None,
              'future_join_count': None, 'future_join_reason': 'Requires matched decision IDs and clock-normalized joins; bucket offsets alone are not affected-join counts.'}
    con = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    con.execute('PRAGMA query_only=ON')
    con.execute('BEGIN')
    try:
        actual = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result['table_names'] = sorted(actual)
        for table in TABLES:
            if table not in actual:
                continue
            info = list(con.execute(f'PRAGMA table_info({identifier(table)})'))
            columns = {r[1] for r in info}
            expressions = ['COUNT(*)']
            keys = ['rows']
            for name in TIMES:
                if name in columns:
                    q = identifier(name)
                    expressions += [f'MIN({q})', f'MAX({q})', f'SUM({q} IS NULL)']
                    keys += [name + '_min', name + '_max', name + '_nulls']
            if 'clock_offset_ms' in columns:
                expressions += ['MIN(clock_offset_ms)', 'MAX(clock_offset_ms)',
                                f'SUM(ABS(clock_offset_ms) > {int(clock_limit_ms)})',
                                'SUM(clock_offset_ms IS NULL)']
                keys += ['clock_offset_min', 'clock_offset_max', 'clock_offset_outside_limit', 'clock_offset_unknown']
            if {'candle_start_ms', 'timeframe_sec', 'received_at_ms', 'finalized'} <= columns:
                expressions += ['SUM(finalized=1 AND received_at_ms < candle_start_ms+timeframe_sec*1000)']
                keys += ['finalized_but_last_receipt_before_source_end']
            values = con.execute(f'SELECT {", ".join(expressions)} FROM {identifier(table)}').fetchone()
            entry = {'columns': sorted(columns), **dict(zip(keys, values))}
            if {'instrument_type'} <= columns:
                entry['product_counts'] = dict(con.execute(f'SELECT instrument_type,COUNT(*) FROM {identifier(table)} GROUP BY instrument_type'))
            if {'source'} <= columns:
                entry['source_counts'] = dict(con.execute(f'SELECT source,COUNT(*) FROM {identifier(table)} GROUP BY source'))
            if 'timeframe_sec' in columns:
                entry['timeframe_counts'] = dict(con.execute(f'SELECT timeframe_sec,COUNT(*) FROM {identifier(table)} GROUP BY timeframe_sec'))
            result['tables'][table] = entry
    finally:
        con.rollback()
        con.close()
    sidecars = [p for p in (Path(str(path)+'-wal'),) if p.exists()]
    result['wal_present'] = bool(sidecars)
    if hash_input:
        result['source_sha256'] = sha256(path)
        result['wal_sha256'] = {p.name: sha256(p) for p in sidecars}
    after = path.stat()
    result['file_metadata_stable_during_audit'] = (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    result['snapshot_claim'] = 'read_transaction_only' if sidecars or not result['file_metadata_stable_during_audit'] else 'stable_main_file'
    result['blocked_claims'] = ['broker_accepted_win_rate', 'actual_expiry_or_strike_parity', 'fresh_holdout', 'live_profitability']
    result['limitations'] = ['Stored final candle values do not prove when finalization was observed.',
                            'Rows overwritten inside observation buckets cannot be reconstructed.',
                            'Price rows without product identity require an explicit proxy mapping.',
                            'Clock anomaly threshold is an engineering exclusion, not a measured profit optimum.',
                            'A live WAL/main-file hash is not a consistent database export; retain the snapshot qualification.']
    return result


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--clock-limit-ms', type=int, default=15_000)
    args=parser.parse_args()
    reports=[]
    for path in args.database:
        start=time.monotonic()
        print(json.dumps({'event':'otc_archive_audit','database':str(path),'state':'reading'}),flush=True)
        reports.append(inspect_database(path,clock_limit_ms=args.clock_limit_ms))
        write_json(args.output, {'schema_version':'otc_audit_v1','databases':reports})
        print(json.dumps({'event':'otc_archive_audit','database':str(path),'state':'complete','seconds':round(time.monotonic()-start,3)}),flush=True)


if __name__=='__main__':
    main()
