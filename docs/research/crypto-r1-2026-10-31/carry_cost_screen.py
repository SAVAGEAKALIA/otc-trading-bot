"""Funding-only development screen using the previously collected R1 snapshot."""
import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

DAY_MS = 86400000
START, END = date(2026, 8, 2), date(2026, 10, 31)
SYMBOLS = ('BTCUSDT', 'ETHUSDT')
FEE_CASES = tuple(map(Decimal, ('0', '15', '24', '31', '62')))


def window_bps(events, cutoff):
    return sum((rate for ts, rate in events if cutoff - 7 * DAY_MS <= ts < cutoff), Decimal(0)) * 10000


def clears(funding_bps, trading_bps, other_bps=Decimal(0)):
    return funding_bps > 2 * trading_bps + other_bps


def screen(raw):
    manifest = (raw / 'manifest.json').read_bytes()
    events = {symbol: {} for symbol in SYMBOLS}
    evidence = []
    for row in json.loads(manifest):
        url = urlsplit(row['url'])
        if url.netloc != 'api.bybit.com' or url.path != '/v5/market/funding/history':
            continue
        symbol = parse_qs(url.query)['symbol'][0]
        if symbol not in events:
            continue
        payload = (raw / row['file']).read_bytes()
        if hashlib.sha256(payload).hexdigest() != row['sha256'] or len(payload) != row['bytes']:
            raise ValueError('funding response does not match manifest')
        data = json.loads(payload)
        if data['retCode'] != 0:
            raise ValueError('funding response failed')
        evidence.append({'file': row['file'], 'sha256': row['sha256']})
        for event in data['result']['list']:
            ts = int(event['fundingRateTimestamp'])
            rate = Decimal(event['fundingRate'])
            if event['symbol'] != symbol or not rate.is_finite() or ts in events[symbol]:
                raise ValueError('invalid or duplicate funding observation')
            events[symbol][ts] = rate
    start_ms = int(datetime.combine(START, datetime.min.time(), timezone.utc).timestamp()) * 1000
    end_ms = start_ms + (END - START).days * DAY_MS
    results = {}
    for symbol, by_time in events.items():
        # Verify this snapshot's observed grid. This is not a venue cadence rule.
        if sorted(by_time) != list(range(start_ms, end_ms, DAY_MS // 3)):
            raise ValueError('unexpected observed funding grid')
        rows = []
        for offset in range(7, (END - START).days):
            day = START + timedelta(days=offset)
            value = window_bps(by_time.items(), start_ms + offset * DAY_MS)
            rows.append({'decision_date': day.isoformat(), 'funding_bps': str(value)})
        values = [Decimal(row['funding_bps']) for row in rows]
        results[symbol] = {
            'decisions': len(rows), 'settlements': len(by_time),
            'max_funding_bps': str(max(values)),
            'max_dates': [r['decision_date'] for r in rows if Decimal(r['funding_bps']) == max(values)],
            'min_funding_bps': str(min(values)),
            'max_roundtrip_cost_ceiling_bps_exclusive': str(max(values) / 2),
            'pass_counts': {str(fee): sum(clears(v, fee) for v in values) for fee in FEE_CASES},
            'rows': rows,
        }
    return {'scope': 'funding-only development diagnostic, hypothetical costs',
            'funding_manifest_sha256': hashlib.sha256(manifest).hexdigest(),
            'source_responses': evidence, 'other_cost_bps': '0',
            'roundtrip_cost_cases_bps': [str(fee) for fee in FEE_CASES],
            'results': results, 'r2_freeze_ready': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(screen(args.raw), indent=2) + '\n')
