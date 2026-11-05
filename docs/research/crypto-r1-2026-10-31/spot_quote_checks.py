"""Probe verified spot archives at D3 decision windows without simulating fills."""
import argparse
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'services/archive_transfer_r1'))
from audit import Book


def decision_keys(preview):
    return sorted({(symbol, date.fromisoformat(day) + timedelta(days=1))
                   for symbol, rows in preview['results'].items()
                   for row in rows
                   for kind in ('entry_condition_dates', 'exit_condition_dates')
                   for day in row[kind]})


def probe(file, symbol, target):
    if symbol not in ('BTCUSDT', 'ETHUSDT') or type(target) is not int or target < 0:
        raise ValueError('invalid probe symbol or timestamp')
    receipt = json.loads(file.with_name(file.name + '.verified.json').read_text())
    if (not isinstance(receipt, dict) or type(receipt.get('size')) is not int
            or receipt['size'] <= 0 or receipt.get('zip_crc_verified') is not True
            or not isinstance(receipt.get('sha256'), str)):
        raise ValueError('invalid archive verification receipt')
    with file.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if (digest != receipt['sha256'] or file.stat().st_size != receipt['size']
            or receipt['zip_crc_verified'] is not True):
        raise ValueError('archive identity or verification mismatch')
    book = Book()
    previous = None
    with zipfile.ZipFile(file) as archive:
        members = archive.infolist()
        if (len(members) != 1 or members[0].is_dir() or members[0].flag_bits & 1
                or members[0].file_size > 20_000_000_000):
            raise ValueError('expected one supported archive member')
        with archive.open(members[0]) as raw, io.BufferedReader(raw) as stream:
            while line := stream.readline(1_000_001):
                if len(line) > 1_000_000:
                    raise ValueError('oversized message')
                row = json.loads(line)
                if not isinstance(row, dict) or not isinstance(row.get('data'), dict):
                    raise ValueError('message must have data object')
                data, kind = row['data'], row.get('type')
                ts, update, seq = row.get('ts'), data.get('u'), data.get('seq')
                snapshot = kind == 'snapshot'
                if (data.get('s') != symbol or row.get('topic') != f'orderbook.200.{symbol}'
                        or kind not in ('snapshot', 'delta')
                        or any(type(x) is not int or x < 0 for x in (ts, update, seq))
                        or (previous is None and (not snapshot or ts // 86400000 != target // 86400000))):
                    raise ValueError('invalid message identity')
                if previous is not None and (ts < previous[0] or (
                        not snapshot and (update < previous[1] or seq < previous[2]))):
                    raise ValueError('archive ordering anomaly before quote')
                if ts > target + 60_000:
                    break
                book.apply(data, snapshot)
                previous = (ts, update, seq)
                if ts >= target:
                    bid, ask = book.best('b'), book.best('a')
                    if bid is not None and ask is not None and bid < ask:
                        return dict(status='observed', archive_sha256=digest, offset_ms=ts-target,
                                    ts_ms=ts, bid=str(bid), ask=str(ask),
                                    bid_size=str(book.levels['b'][bid]), ask_size=str(book.levels['a'][ask]),
                                    spread_bps=str((ask-bid)*Decimal(20000)/(ask+bid)))
    if previous is None:
        raise ValueError('empty archive or no initial snapshot before deadline')
    return dict(status='no_valid_update_in_window', archive_sha256=digest)


def build(preview, directories):
    result = []
    for symbol, day in decision_keys(preview):
        target = int(datetime.combine(day, time(0, 10), timezone.utc).timestamp()) * 1000
        name = f'spot-{day}_{symbol}_ob200.data.zip'
        paths = [directory / name for directory in directories if (directory / name).is_file()]
        row = dict(symbol=symbol, decision_date=str(day), target_ms=target)
        if len(paths) > 1:
            raise ValueError('ambiguous archive source')
        if not paths:
            row['status'] = 'archive_unavailable'
        elif not paths[0].with_name(name + '.verified.json').is_file():
            row['status'] = 'archive_unverified'
        else:
            row.update(probe(paths[0], symbol, target))
        result.append(row)
    return dict(scope='archived exchange timestamp quote checks', rows=result, fills_simulated=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('preview', type=Path)
    parser.add_argument('directories', type=Path, nargs='+')
    args = parser.parse_args()
    print(json.dumps(build(json.loads(args.preview.read_text()), args.directories), indent=2))
