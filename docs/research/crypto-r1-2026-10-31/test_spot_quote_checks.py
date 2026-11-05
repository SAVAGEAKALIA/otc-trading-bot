import copy
from datetime import datetime, time, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from spot_quote_checks import build, decision_keys, probe

EVIDENCE_DIR = Path(__file__).resolve().parent


class SavedQuoteEvidenceTest(unittest.TestCase):
    def test_saved_evidence_covers_every_target_with_observed_quotes(self):
        preview = json.loads((EVIDENCE_DIR / 'spot_trend_preview.json').read_text())
        evidence = json.loads((EVIDENCE_DIR / 'spot_quote_checks.json').read_text())
        expected = {(symbol, str(day)): int(datetime.combine(
            day, time(0, 10), timezone.utc).timestamp()) * 1000
            for symbol, day in decision_keys(preview)}
        self.assertIs(evidence['fills_simulated'], False)
        self.assertEqual(len(evidence['rows']), len(expected))
        self.assertEqual({(row['symbol'], row['decision_date'])
                          for row in evidence['rows']}, set(expected))
        for row in evidence['rows']:
            with self.subTest(symbol=row['symbol'], day=row['decision_date']):
                self.assertEqual(row['status'], 'observed')
                self.assertEqual(row['target_ms'], expected[row['symbol'], row['decision_date']])
                self.assertEqual(row['offset_ms'], row['ts_ms'] - row['target_ms'])
                self.assertGreaterEqual(row['offset_ms'], 0)
                self.assertLessEqual(row['offset_ms'], 60_000)


def message(ts, kind='delta', update=2, asks=None, bids=None):
    return {'topic': 'orderbook.200.BTCUSDT', 'type': kind, 'ts': ts,
            'data': {'s': 'BTCUSDT', 'u': update, 'seq': update,
                     'a': [['11', '1']] if asks is None else asks,
                     'b': [['10', '2']] if bids is None else bids}}


class QuoteChecksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'sample.zip'

    def fixture(self, rows, members=None):
        with zipfile.ZipFile(self.path, 'w') as archive:
            for name, content in (members or [('sample.data', '\n'.join(map(json.dumps, rows)))]):
                archive.writestr(name, content)
        self.receipt = self.path.with_name(self.path.name + '.verified.json')
        self.receipt.write_text(json.dumps({
            'sha256': hashlib.sha256(self.path.read_bytes()).hexdigest(),
            'size': self.path.stat().st_size, 'zip_crc_verified': True,
        }))
        return self.path

    def initial(self):
        return message(1, 'snapshot', 1)

    def test_uses_new_update_and_enforces_inclusive_deadline(self):
        path = self.fixture([self.initial(), message(60_100, asks=[['11', '0'], ['12', '1']])])
        row = probe(path, 'BTCUSDT', 100)
        self.assertEqual((row['ask'], row['offset_ms']), ('12', 60_000))
        self.assertEqual(probe(path, 'BTCUSDT', 99)['status'], 'no_valid_update_in_window')

    def test_stale_book_never_becomes_a_quote(self):
        path = self.fixture([self.initial()])
        self.assertEqual(probe(path, 'BTCUSDT', 100)['status'], 'no_valid_update_in_window')

    def test_snapshot_replaces_old_levels(self):
        path = self.fixture([self.initial(), message(100, 'snapshot', 0,
                                                    asks=[['13', '4']], bids=[['12', '3']])])
        row = probe(path, 'BTCUSDT', 100)
        self.assertEqual((row['bid'], row['ask'], row['ask_size']), ('12', '13', '4'))

    def test_locked_crossed_and_empty_books_wait_for_valid_update(self):
        for bad_asks in ([['11', '0']], [['11', '0'], ['10', '2']], [['11', '0'], ['9', '2']]):
            with self.subTest(asks=bad_asks):
                path = self.fixture([self.initial(), message(100, asks=bad_asks),
                                     message(101, 'snapshot', 1, asks=[['12', '3']])])
                row = probe(path, 'BTCUSDT', 100)
                self.assertEqual((row['offset_ms'], row['ask']), (1, '12'))

    def test_rejects_missing_snapshot_and_wrong_day(self):
        for first in (message(1), message(86_400_000, 'snapshot', 1)):
            with self.subTest(first=first):
                with self.assertRaisesRegex(ValueError, 'identity'):
                    probe(self.fixture([first]), 'BTCUSDT', 100)

    def test_rejects_backward_timestamp_update_or_sequence(self):
        for field, value in (('ts', 0), ('u', 0), ('seq', 0)):
            later = message(100)
            (later if field == 'ts' else later['data'])[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'ordering'):
                probe(self.fixture([self.initial(), later]), 'BTCUSDT', 100)

    def test_rejects_malformed_message_objects(self):
        for bad in (None, [], {}, {'data': []}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'data object'):
                probe(self.fixture([bad]), 'BTCUSDT', 100)

    def test_rejects_bad_identity_and_noninteger_timestamps(self):
        for field, value in (('ts', True), ('ts', -1), ('ts', '1'),
                             ('topic', 'orderbook.50.BTCUSDT'), ('type', 'unknown')):
            bad = self.initial()
            bad[field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, 'identity'):
                probe(self.fixture([bad]), 'BTCUSDT', 100)
        bad = self.initial()
        bad['data']['s'] = 'ETHUSDT'
        with self.assertRaisesRegex(ValueError, 'identity'):
            probe(self.fixture([bad]), 'BTCUSDT', 100)

    def test_rejects_invalid_book_values(self):
        for levels in ([['NaN', '1']], [['11', '-1']], [['0', '1']],
                       [['11', '1'], ['11.0', '2']], [['11', 1]]):
            with self.subTest(levels=levels), self.assertRaises(ValueError):
                probe(self.fixture([message(1, 'snapshot', 1, asks=levels)]), 'BTCUSDT', 100)

    def test_rejects_receipt_or_archive_tampering(self):
        path = self.fixture([self.initial()])
        original = json.loads(self.receipt.read_text())
        for field, value in (('sha256', '0' * 64), ('size', original['size'] + 1),
                             ('zip_crc_verified', False), ('size', True)):
            changed = copy.deepcopy(original)
            changed[field] = value
            self.receipt.write_text(json.dumps(changed))
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                probe(path, 'BTCUSDT', 100)
        self.receipt.write_text(json.dumps(original))
        path.write_bytes(path.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            probe(path, 'BTCUSDT', 100)

    def test_rejects_empty_oversized_and_multiple_members(self):
        for members in ([('a', '')], [('a/', '')], [('a', '{}'), ('b', '{}')],
                        [('a', ' ' * 1_000_001)]):
            with self.subTest(members=[x[0] for x in members]), self.assertRaises(ValueError):
                probe(self.fixture([], members), 'BTCUSDT', 100)

    def test_next_day_deduplication(self):
        row = {'entry_condition_dates': ['2026-10-30'], 'exit_condition_dates': ['2026-10-30']}
        keys = decision_keys({'results': {'BTCUSDT': [row, row]}})
        self.assertEqual([(symbol, str(day)) for symbol, day in keys], [('BTCUSDT', '2026-10-31')])

    def test_unverified_and_missing_archives_are_reported(self):
        preview = {'results': {'BTCUSDT': [{
            'entry_condition_dates': ['2026-10-30'], 'exit_condition_dates': []
        }]}}
        self.assertEqual(build(preview, [self.root])['rows'][0]['status'], 'archive_unavailable')
        (self.root / 'spot-2026-10-31_BTCUSDT_ob200.data.zip').write_bytes(b'partial')
        row = build(preview, [self.root])['rows'][0]
        self.assertEqual(row['status'], 'archive_unverified')
        self.assertEqual(row['target_ms'], 1793405400000)
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            build(preview, [self.root, self.root])

    def test_rejects_invalid_probe_parameters(self):
        for symbol, target in (('BAD', 100), ('BTCUSDT', True), ('BTCUSDT', -1)):
            with self.subTest(symbol=symbol, target=target), self.assertRaisesRegex(ValueError, 'probe'):
                probe(self.path, symbol, target)
