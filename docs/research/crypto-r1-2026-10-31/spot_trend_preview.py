"""Audit D3 lookback coverage and count threshold conditions without simulating trades."""
import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

LOOKBACKS = ((20, 10), (55, 20), (100, 50))
START = datetime(2026, 4, 24, tzinfo=timezone.utc)
DAY_MS = 86400000


def conditions(bars, index, entry, exit_):
    if index < max(entry, exit_):
        raise ValueError('missing warm-up')
    close = bars[index][3]
    return (close > max(bar[1] for bar in bars[index-entry:index]),
            close < min(bar[2] for bar in bars[index-exit_:index]))


def preview(directory):
    source = json.loads((directory / 'report.json').read_text())
    outputs = {}
    start_ms = int(START.timestamp()) * 1000
    grid = list(range(start_ms, start_ms + 190 * DAY_MS, DAY_MS))
    for record in source['records']:
        symbol = record['symbol']
        if symbol not in ('BTCUSDT', 'ETHUSDT') or symbol in outputs:
            raise ValueError('unexpected symbol')
        raw = (directory / (symbol + '.json')).read_bytes()
        if len(raw) != record['bytes'] or hashlib.sha256(raw).hexdigest() != record['sha256']:
            raise ValueError('spot response hash or length mismatch')
        payload = json.loads(raw)
        result = payload['result']
        if payload['retCode'] != 0 or result['symbol'] != symbol or result['category'] != 'spot':
            raise ValueError('unexpected spot response')
        rows = sorted(result['list'], key=lambda row: int(row[0]))
        if [int(row[0]) for row in rows] != grid:
            raise ValueError('daily grid differs from expected UTC coverage')
        bars = []
        for row in rows:
            o, h, l, c, v, t = map(Decimal, row[1:])
            if not all(x.is_finite() for x in (o, h, l, c, v, t)) or not (
                    0 < l <= min(o, c) <= max(o, c) <= h and min(v, t) >= 0):
                raise ValueError('invalid OHLC or volume')
            bars.append((o, h, l, c))
        components = []
        for entry, exit_ in LOOKBACKS:
            entry_days, exit_days = [], []
            for index in range(100, len(bars)):
                buy, sell = conditions(bars, index, entry, exit_)
                day = (START + timedelta(days=index)).date().isoformat()
                if buy:
                    entry_days.append(day)
                if sell:
                    exit_days.append(day)
            components.append(dict(entry_lookback=entry, exit_lookback=exit_, eligible_signal_days=90,
                                   entry_condition_dates=entry_days, exit_condition_dates=exit_days))
        outputs[symbol] = components
    if outputs.keys() != {'BTCUSDT', 'ETHUSDT'}:
        raise ValueError('missing symbol')
    return dict(scope='historical threshold preview only', source=source, warmup_start='2026-04-24',
                signal_first='2026-08-02', signal_last='2026-10-30',
                decision_first='2026-08-03T00:05:00Z', decision_last='2026-10-31T00:05:00Z',
                results=outputs, r2_freeze_ready=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(preview(args.directory), indent=2))
