"""Full-file descriptive replay of Bybit public depth archives; no execution claims."""
from __future__ import annotations
import argparse, heapq, hashlib, io, json, time, zipfile
from collections import Counter
from functools import lru_cache
from decimal import Decimal, InvalidOperation
from pathlib import Path

class AuditError(ValueError):
    pass

def integer(value):
    if type(value) is not int or value < 0:
        raise AuditError('expected nonnegative integer')
    return value

def number(value, positive=False):
    if not isinstance(value, str) or len(value) > 100:
        raise AuditError('price and size must be decimal strings')
    return _parse_number(value, positive)

@lru_cache(maxsize=8192)
def _parse_number(value, positive):
    try:
        v = Decimal(value)
    except InvalidOperation as exc:
        raise AuditError('invalid decimal') from exc
    if not v.is_finite() or not -100 <= v.as_tuple().exponent <= 100 or v < 0 or (positive and v == 0):
        raise AuditError('invalid price or size')
    return v

class Book:

    def __init__(self):
        self.reset()

    def reset(self):
        self.levels = {'a': {}, 'b': {}}
        self.heaps = {'a': [], 'b': []}

    def apply(self, data, snapshot):
        if snapshot:
            self.reset()
        for side in ('a', 'b'):
            updates = data.get(side)
            if not isinstance(updates, list):
                raise AuditError('missing side')
            seen = set()
            for row in updates:
                if not isinstance(row, list) or len(row) != 2:
                    raise AuditError('invalid price level')
                price, size = (number(row[0], True), number(row[1]))
                if price in seen:
                    raise AuditError('duplicate price in message side')
                seen.add(price)
                if size == 0:
                    self.levels[side].pop(price, None)
                else:
                    if price not in self.levels[side]:
                        heapq.heappush(self.heaps[side], price if side == 'a' else price.copy_negate())
                    self.levels[side][price] = size
            if len(self.levels[side]) > 10000:
                raise AuditError('book level limit exceeded')
            if len(self.heaps[side]) > 4 * len(self.levels[side]) + 100:
                self.heaps[side] = [x if side == 'a' else x.copy_negate() for x in self.levels[side]]
                heapq.heapify(self.heaps[side])

    def best(self, side):
        heap = self.heaps[side]
        while heap and (heap[0] if side == 'a' else heap[0].copy_negate()) not in self.levels[side]:
            heapq.heappop(heap)
        return (heap[0] if side == 'a' else heap[0].copy_negate()) if heap else None

def audit(path: Path, symbol: str, start: int, end: int, progress=None):
    if symbol not in ('BTCUSDT', 'ETHUSDT') or type(start) is not int or type(end) is not int or (not 0 < end - start <= 86400000):
        raise AuditError('invalid audit window/symbol')
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1048576), b''):
            digest.update(chunk)
    book = Book()
    counts = Counter()
    minutes = Counter()
    first = last = prev_u = prev_seq = None
    maxgap = 0
    valid = False
    examples = []
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) != 1 or members[0].is_dir() or members[0].flag_bits & 1 or (members[0].file_size > 20000000000):
            raise AuditError('unsupported archive members/size')
        member = members[0]
        with archive.open(member) as raw, io.BufferedReader(raw, buffer_size=1048576) as handle:
            while True:
                line = handle.readline(1000001)
                if not line:
                    break
                if len(line) > 1000000:
                    raise AuditError('oversize JSON line')
                try:
                    x = json.loads(line)
                except (ValueError, TypeError) as exc:
                    raise AuditError('invalid JSON message') from exc
                if not isinstance(x, dict) or not isinstance(x.get('data'), dict):
                    raise AuditError('message must have data object')
                data = x['data']
                kind = x.get('type')
                if kind not in ('snapshot', 'delta') or data.get('s') != symbol or x.get('topic') != 'orderbook.200.' + symbol:
                    raise AuditError('wrong message identity')
                stamp = integer(x.get('ts'))
                u = integer(data.get('u'))
                seq = integer(data.get('seq'))
                if 'cts' in x:
                    integer(x['cts'])
                counts['messages'] += 1
                counts[kind] += 1
                if first is None:
                    first = stamp
                    if kind != 'snapshot':
                        raise AuditError('archive must begin with snapshot')
                anomalies = []
                if not start <= stamp < end:
                    counts['outside_window'] += 1
                    anomalies.append('outside_window')
                if last is not None:
                    maxgap = max(maxgap, stamp - last)
                    if stamp < last:
                        counts['backward_ts'] += 1
                        anomalies.append('backward_ts')
                    if kind == 'delta' and (u < prev_u or seq < prev_seq):
                        counts['delta_order_rewind'] += 1
                        anomalies.append('delta_order_rewind')
                if anomalies:
                    valid = False
                    if len(examples) < 10:
                        examples.append({'message': counts['messages'], 'ts': stamp, 'reasons': anomalies})
                if kind == 'snapshot' and (not anomalies):
                    valid = True
                # Inspect numeric fields even while book state is tainted.
                book.apply(data, kind == 'snapshot')
                if valid:
                    ask, bid = (book.best('a'), book.best('b'))
                    if ask is None or bid is None:
                        counts['empty_states'] += 1
                    elif bid >= ask:
                        counts['locked_crossed_states'] += 1
                    counts['replayed_valid_states'] += 1
                else:
                    counts['untrusted_states'] += 1
                if start <= stamp < end:
                    minutes[(stamp - start) // 60000] += 1
                last, prev_u, prev_seq = (stamp, u, seq)
                if progress and counts['messages'] % 100000 == 0:
                    progress(counts['messages'], handle.tell(), member.file_size)
            if handle.tell() != member.file_size:
                raise AuditError('ZIP member size differs from bytes read')
        if not counts['messages']:
            raise AuditError('empty archive')
    return {'file': str(path), 'sha256': digest.hexdigest(), 'compressed_bytes': path.stat().st_size, 'uncompressed_bytes': member.file_size, 'zip_crc_verified': True, 'counts': dict(counts), 'first_ts_ms': first, 'last_ts_ms': last, 'largest_observed_ts_gap_ms': maxgap, 'observed_minutes': len(minutes), 'anomaly_examples': examples, 'all_messages_processed': True, 'sequence_completeness_proven': False, 'fill_or_liquidation_validated': False}
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('file', type=Path)
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--start-ms', type=int, required=True)
    parser.add_argument('--end-ms', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output already exists')
    started = time.monotonic()

    def progress(n, done, total):
        rate = done / (time.monotonic() - started)
        print(json.dumps({'event': 'R1 full archive audit', 'file': args.file.name, 'timestamp': time.time(), 'messages': n, 'bytes': done, 'total': total, 'percent': 100 * done / total, 'eta_seconds': (total - done) / rate}), flush=True)
    result = audit(args.file, args.symbol, args.start_ms, args.end_ms, progress)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
