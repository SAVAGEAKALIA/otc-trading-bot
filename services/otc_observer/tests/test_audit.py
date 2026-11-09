from pathlib import Path
import sqlite3
import tempfile
import unittest
from services.otc_observer.audit import inspect_database, identifier


class AuditTests(unittest.TestCase):
    def test_transaction_source_hash_column_inventory_and_clock_anomalies(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'source.sqlite';con=sqlite3.connect(path)
            con.execute('PRAGMA synchronous=OFF')
            con.execute('CREATE TABLE quote_samples (source_event_ms INTEGER, received_at_ms INTEGER, clock_offset_ms INTEGER)')
            con.executemany('INSERT INTO quote_samples VALUES (?,?,?)',[(100,110,0),(200,210,20000),(300,None,None)])
            con.commit();con.close()
            result=inspect_database(path)
            self.assertTrue(result['read_only']);self.assertEqual(len(result['source_sha256']),64)
            self.assertEqual(result['tables']['quote_samples']['rows'],3)
            self.assertEqual(result['tables']['quote_samples']['received_at_ms_nulls'],1)
            self.assertEqual(result['tables']['quote_samples']['clock_offset_outside_limit'],1)
            self.assertEqual(result['tables']['quote_samples']['clock_offset_unknown'],1)
            self.assertIsNone(result['future_join_count'])
            self.assertIn('broker_accepted_win_rate',result['blocked_claims'])
            self.assertEqual(identifier('a"b'),'"a""b"')
            with self.assertRaises(ValueError):inspect_database(path,clock_limit_ms=-1)

    def test_missing_table_stays_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'source.sqlite';con=sqlite3.connect(path);con.execute('PRAGMA synchronous=OFF');con.execute('CREATE TABLE other (n INTEGER)');con.commit();con.close()
            result=inspect_database(path,hash_input=False)
            self.assertEqual(result['tables'],{});self.assertIsNone(result['source_sha256'])


if __name__=='__main__':unittest.main()
