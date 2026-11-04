import tempfile, unittest, zipfile, json
from pathlib import Path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit import audit, AuditError, Book

def message(t=1, kind='snapshot', bid='10', ask='11', u=1):
    return {'topic': 'orderbook.200.BTCUSDT', 'type': kind, 'ts': t, 'data': {'s': 'BTCUSDT', 'b': [[bid, '1']], 'a': [[ask, '1']], 'u': u, 'seq': u}}

class AuditTests(unittest.TestCase):

    def run_rows(self, rows):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'a.zip'
            with zipfile.ZipFile(p, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr('x.data', '\n'.join(map(json.dumps, rows)))
            return audit(p, 'BTCUSDT', 0, 60000)

    def test_replay_and_crc(self):
        r = self.run_rows([message(), message(2, 'delta', u=2)])
        self.assertTrue(r['zip_crc_verified'])
        self.assertEqual(r['counts']['replayed_valid_states'], 2)

    def test_first_delta_rejected(self):
        with self.assertRaises(AuditError):
            self.run_rows([message(kind='delta')])

    def test_rewind_invalid_until_snapshot(self):
        r = self.run_rows([message(t=2, u=2), message(t=1, kind='delta'), message(t=3, kind='delta', u=3), message(t=4, u=4)])
        self.assertEqual(r['counts']['untrusted_states'], 2)
        self.assertEqual(r['counts']['replayed_valid_states'], 2)

    def test_invalid_numbers_and_boolean(self):
        for value in ('NaN', 'Infinity', '0', '-1'):
            with self.subTest(value=value), self.assertRaises(AuditError):
                self.run_rows([message(bid=value)])
        with self.assertRaises(AuditError):
            self.run_rows([message(t=True)])

    def test_crossed_is_reported(self):
        self.assertEqual(self.run_rows([message(bid='12')])['counts']['locked_crossed_states'], 1)

    def test_snapshot_replaces_and_zero_deletes(self):
        b = Book()
        b.apply({'a': [['11', '1']], 'b': [['10', '1'], ['9', '1']]}, True)
        b.apply({'a': [], 'b': [['10', '0']]}, False)
        self.assertEqual(str(b.best('b')), '9')
        b.apply({'a': [['13', '1']], 'b': [['12', '1']]}, True)
        self.assertNotIn(9, b.levels['b'])

    def test_heap_bounded(self):
        b = Book()
        b.apply({'a': [['11', '1']], 'b': [['10', '1']]}, True)
        for i in range(2000):
            b.apply({'a': [[str(12 + i), '1']], 'b': []}, False)
            b.apply({'a': [[str(12 + i), '0']], 'b': []}, False)
        self.assertLess(len(b.heaps['a']), 110)

    def test_seq_gaps_are_not_missing_proof(self):
        self.assertNotIn('delta_order_rewind', self.run_rows([message(u=10), message(2, 'delta', u=20)])['counts'])

    def test_exact_bid_precision(self):
        b = Book()
        price = '10.123456789012345678901234567891'
        b.apply({'a': [['11', '1']], 'b': [[price, '1']]}, True)
        self.assertEqual(str(b.best('b')), price)

    def test_corrupted_zip_crc(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'a.zip'
            with zipfile.ZipFile(p, 'w') as z:
                z.writestr('x.data', json.dumps(message()))
            raw = p.read_bytes()
            p.write_bytes(raw.replace(b'"ts": 1', b'"ts": 2', 1))
            with self.assertRaises(zipfile.BadZipFile):
                audit(p, 'BTCUSDT', 0, 60000)

    def test_zip_member_size_mismatch(self):
        import struct
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('events.data', json.dumps(message()))
            raw = bytearray(path.read_bytes())
            offset = raw.index(b'PK\x01\x02') + 24
            size = struct.unpack_from('<I', raw, offset)[0]
            struct.pack_into('<I', raw, offset, size + 100)
            path.write_bytes(raw)
            with self.assertRaisesRegex(AuditError, 'size differs'):
                audit(path, 'BTCUSDT', 0, 60000)
if __name__ == '__main__':
    unittest.main()
