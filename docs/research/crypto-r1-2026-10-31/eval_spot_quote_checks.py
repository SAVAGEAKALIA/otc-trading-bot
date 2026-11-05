"""Offline quote eval: independent replay oracle and adverse inputs; 100% required.

Uses only Python's standard library and synthetic archives. It does not evaluate
trading performance or turn exchange event timestamps into client receipt times.
"""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import random
import tempfile
import zipfile

from spot_quote_checks import probe


def write_archive(root, rows):
    path = root / 'scenario.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('scenario.data', '\n'.join(json.dumps(row) for row in rows))
    path.with_name(path.name + '.verified.json').write_text(json.dumps({
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'size': path.stat().st_size, 'zip_crc_verified': True,
    }))
    return path


def oracle(rows, target):
    """Deliberately simple dictionary replay, independent of the production Book."""
    sides = {'a': {}, 'b': {}}
    for row in rows:
        if row['ts'] > target + 60_000:
            break
        if row['type'] == 'snapshot':
            sides = {'a': {}, 'b': {}}
        for side, book in sides.items():
            for price, quantity in row['data'][side]:
                price, quantity = Decimal(price), Decimal(quantity)
                if quantity == 0:
                    book.pop(price, None)
                else:
                    book[price] = quantity
        if row['ts'] < target or not all(sides.values()):
            continue
        bid, ask = max(sides['b']), min(sides['a'])
        if bid < ask:
            return {'status': 'observed', 'ts_ms': row['ts'], 'offset_ms': row['ts'] - target,
                    'bid': str(bid), 'ask': str(ask), 'bid_size': str(sides['b'][bid]),
                    'ask_size': str(sides['a'][ask]),
                    'spread_bps': str((ask - bid) / ((bid + ask) / 2) * 10000)}
    return {'status': 'no_valid_update_in_window'}


def row(ts, sequence, snapshot=False, asks=None, bids=None):
    return {'topic': 'orderbook.200.BTCUSDT', 'type': 'snapshot' if snapshot else 'delta',
            'ts': ts, 'data': {'s': 'BTCUSDT', 'u': sequence, 'seq': sequence,
                              'a': asks if asks is not None else [['101', '1']],
                              'b': bids if bids is not None else [['99', '2']]}}


def run():
    rng = random.Random(20261105)
    results = []
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for scenario in range(96):
            target = 100_000
            rows = [row(1, 1, True)]
            for sequence, ts in enumerate(sorted(rng.sample(range(2, 200_001), 30)), 2):
                rows.append(row(ts, sequence, rng.randrange(8) == 0,
                                [[str(rng.randrange(99, 106)), str(rng.randrange(4))]],
                                [[str(rng.randrange(96, 103)), str(rng.randrange(4))]]))
            expected = oracle(rows, target)
            actual = probe(write_archive(root, rows), 'BTCUSDT', target)
            for field, value in expected.items():
                if field == 'spread_bps':
                    # Different algebraic ordering may round the final Decimal digit.
                    assert abs(Decimal(actual[field]) - Decimal(value)) <= Decimal('1e-23')
                else:
                    assert actual[field] == value, (scenario, field, actual, expected)
            results.append({'case': f'oracle_{scenario}', 'passed': True})
        for offset in (-1, 0, 1, 59_999, 60_000, 60_001):
            rows = [row(1, 1, True), row(100_000 + offset, 2)]
            actual = probe(write_archive(root, rows), 'BTCUSDT', 100_000)
            expected = 'observed' if 0 <= offset <= 60_000 else 'no_valid_update_in_window'
            assert actual['status'] == expected
            results.append({'case': f'boundary_{offset}', 'passed': True})
        for value in ('NaN', 'Infinity', '-1', '1e101', '1e-101', 'x', 2, None):
            rows = [row(1, 1, True, asks=[['101', value]])]
            try:
                probe(write_archive(root, rows), 'BTCUSDT', 100_000)
            except ValueError:
                results.append({'case': f'invalid_size_{value}', 'passed': True})
            else:
                raise AssertionError(('accepted invalid size', value))
        for field, value in (('ts', True), ('ts', -1), ('u', -1), ('seq', '2')):
            rows = [row(1, 1, True), row(2, 2)]
            (rows[1] if field == 'ts' else rows[1]['data'])[field] = value
            try:
                probe(write_archive(root, rows), 'BTCUSDT', 100_000)
            except ValueError:
                results.append({'case': f'invalid_identity_{field}_{value}', 'passed': True})
            else:
                raise AssertionError(('accepted invalid identity', field, value))
    return {'threshold': 1.0, 'passed': len(results), 'total': len(results),
            'pass_rate': 1.0, 'fills_simulated': False, 'cases': results}


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
