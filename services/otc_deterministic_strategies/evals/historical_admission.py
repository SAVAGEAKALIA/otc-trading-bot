"""Read-only coverage audit. Missing offer/contract evidence prevents economics."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time


def utc(ms):
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def audited_read(path):
    path = Path(path).resolve()
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    connection.execute('PRAGMA query_only=ON')
    return connection


def run(candle_db, context_db, output, source_lock=None):
    started = time.perf_counter()
    base = Path(__file__).resolve().parents[1]
    source_lock = Path(source_lock) if source_lock is not None else base / 'source-lock-v5.json'
    lock = json.loads(source_lock.read_text())
    for name, expected in lock['files'].items():
        if hashlib.sha256((base / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Frozen policy changed before historical audit')
    assets = ('EURUSD-OTC', 'GBPUSD-OTC')
    historical = audited_read(candle_db)
    context = audited_read(context_db)
    candle_counts = []
    real_counts = []
    source_states = []
    for asset in assets:
        row = historical.execute('SELECT count(*),min(timestamp),max(timestamp) FROM candles WHERE asset=? AND timeframe=120', (asset,)).fetchone()
        candle_counts.append({'asset': asset, 'bars': row[0], 'first_start_utc': utc(row[1] * 1000 if row[1] is not None else None),
                              'last_start_utc': utc(row[2] * 1000 if row[2] is not None else None),
                              'receiver_timestamp_present': False, 'finalization_receipt_present': False})
        row = context.execute('''SELECT count(*),min(candle_start_ms),max(candle_start_ms),
            sum(finalized=1),sum(received_at_ms<candle_start_ms+timeframe_sec*1000),
            sum(server_at_receive_ms IS NULL),sum(clock_offset_ms IS NULL),
            sum(server_at_receive_ms<candle_start_ms+timeframe_sec*1000)
            FROM realtime_candles WHERE broker_asset=? AND timeframe_sec=120''', (asset,)).fetchone()
        real_counts.append({'asset': asset, 'bars': row[0], 'first_start_utc': utc(row[1]),
                            'last_start_utc': utc(row[2]), 'reported_finalized': row[3],
                            'receiver_report_before_close': row[4], 'missing_broker_clock': row[5],
                            'missing_offset': row[6], 'broker_report_before_close': row[7]})
        quotes = context.execute('SELECT count(*),min(received_at_ms),max(received_at_ms) FROM quote_samples WHERE broker_asset=?', (asset,)).fetchone()
        payouts = context.execute("SELECT count(*),min(received_at_ms),max(received_at_ms) FROM payout_samples WHERE broker_asset=? AND instrument_type='turbo-option'", (asset,)).fetchone()
        source_states.append({'asset': asset, 'quote_rows': quotes[0], 'quote_first_utc': utc(quotes[1]),
                              'quote_last_utc': utc(quotes[2]), 'turbo_payout_rows': payouts[0],
                              'turbo_payout_first_utc': utc(payouts[1]) if payouts[1] else None,
                              'turbo_payout_last_utc': utc(payouts[2]) if payouts[2] else None})
    tables = {item[0] for item in context.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    report = {'schema': 'otc_existing_policy_historical_admission_v1',
              'status': 'BLOCKED_FOR_ECONOMIC_EVIDENCE', 'economic_claim': False,
              'live_or_fresh_model_cohort_used': False, 'admitted_actual_contracts': 0,
              'admitted_economic_opportunities': 0,
              'reason': 'Historical sources lack causally captured positive/negative offer state, offered absolute expiry, accepted strike and broker cash settlement. A payout sample is insufficient offer evidence.',
              'historical_data_role': 'spent exploratory sources; no new verification edge',
              'policies': ['legacy_mhi3_causal', 'legacy_exhaustion_causal'], 'trial_slots': [2, 3],
              'source_sha256': lock['source_sha256'], 'source_registration_sha256': lock['registration_sha256'],
              'historical_candles': candle_counts, 'realtime_candles': real_counts,
              'quotes_and_payouts': source_states, 'context_table_names': sorted(tables),
              'requirements_missing': ['causal_offer_state', 'offered_absolute_expiry',
                                       'accepted_strike', 'accepted_payout', 'broker_cash_settlement'],
              'directional_proxy_scored': False,
              'directional_proxy_reason': 'Full practice-policy qualification cannot be measured; unknown offer eligibility is retained rather than assumed active.',
              'next_measurement': 'Run hash-frozen shadow signals alongside root practice capture, retaining unavailable opportunities. Compare only a separately frozen prospective version with actual offers/contracts.',
              'wall_seconds': time.perf_counter() - started,
              'source_paths': {'candles': str(Path(candle_db).resolve()), 'context': str(Path(context_db).resolve())}}
    historical.close()
    context.close()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as target:
        json.dump(report, target, indent=2)
        target.write('\n')
    print(json.dumps(report, sort_keys=True))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candles', required=True, type=Path)
    parser.add_argument('--context', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--source-lock', type=Path)
    args = parser.parse_args()
    run(args.candles, args.context, args.output, args.source_lock)


if __name__ == '__main__':
    main()
