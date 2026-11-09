from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from services.otc_observer.export import read_snapshot, ASSETS
from services.otc_research.export import export_matrix, sha256, load_boundary


def fixture_database(path):
    decision = int(datetime.fromisoformat('2026-08-01').replace(tzinfo=timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(path)
    con.execute('PRAGMA synchronous=OFF')
    con.execute('CREATE TABLE quote_samples (broker_asset TEXT, source_event_ms INTEGER, received_at_ms INTEGER, clock_offset_ms INTEGER, mid REAL)')
    con.execute('CREATE TABLE mood_samples (broker_asset TEXT, instrument_type TEXT, observed_bucket_ms INTEGER, received_at_ms INTEGER, clock_offset_ms INTEGER, call_fraction REAL)')
    con.execute('CREATE TABLE payout_samples (broker_asset TEXT, instrument_type TEXT, observed_bucket_ms INTEGER, received_at_ms INTEGER, clock_offset_ms INTEGER, payout_fraction REAL, source TEXT)')
    for asset in ASSETS:
        for offset, value in [(-60000, 99), (-100, 100), (1, 100), (119999, 101), (120001, 101)]:
            con.execute('INSERT INTO quote_samples VALUES (?,?,?,?,?)', (asset, decision + offset - 10, decision + offset, 0, value))
        con.execute('INSERT INTO mood_samples VALUES (?,?,?,?,?,?)', (asset, 'turbo-option', decision-200, decision-100, 0, .6))
        con.execute('INSERT INTO payout_samples VALUES (?,?,?,?,?,?,?)', (asset, 'turbo-option', decision-600000, decision-100, 0, .85, 'init-snapshot'))
    con.commit();con.close();return decision


class ExportTests(unittest.TestCase):
    def test_complete_boundary_canonical_matrix_lineage_and_null_contracts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);db = root/'source.sqlite';fixture_database(db)
            before = sha256(db)
            snapshot = read_snapshot(db, root/'observations')
            self.assertEqual(snapshot['source_sha256'], before)
            self.assertTrue(snapshot['source_stable'])
            audit = export_matrix(root/'observations', root/'matrix')
            self.assertEqual(audit['counts']['total'], 4)
            self.assertEqual(audit['counts']['resolved'], 2)
            self.assertEqual(audit['counts']['unresolved'], 2)
            self.assertIsNone(audit['actual_win_rate'])
            self.assertEqual(sha256(db), before)
            matrix_manifest = json.loads((root/'matrix/manifest.json').read_text())
            self.assertEqual(matrix_manifest['input_sha256'], sha256(root/'matrix/matrix.csv'))
            self.assertEqual(matrix_manifest['metadata']['decision_lineage_sha256'], sha256(root/'matrix/decision_lineage.jsonl'))
            self.assertFalse(matrix_manifest['promotable'])
            with self.assertRaises(ValueError): read_snapshot(db, root/'observations')
            with self.assertRaises(ValueError): export_matrix(root/'observations', root/'matrix')

    def test_wal_and_hash_corruption_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);db=root/'source.sqlite';fixture_database(db)
            wal=Path(str(db)+'-wal');wal.write_text('active')
            with self.assertRaises(ValueError):read_snapshot(db,root/'blocked')
            wal.unlink()
            read_snapshot(db,root/'snapshot')
            with (root/'snapshot/observations.jsonl').open('a') as stream:stream.write('{}\n')
            with self.assertRaises(ValueError):load_boundary(root/'snapshot')

    def test_source_mutation_during_extraction_is_blocked(self):
        from unittest.mock import patch
        import services.otc_observer.export as module
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);db=root/'source.sqlite';fixture_database(db)
            original=module.normalize_rows;changed=False
            def mutate(*args,**kwargs):
                nonlocal changed
                value=original(*args,**kwargs)
                if not changed:
                    changed=True
                    # A metadata-only change is enough to revoke source stability.
                    import os
                    os.utime(db, ns=(db.stat().st_atime_ns,db.stat().st_mtime_ns+1))
                return value
            with patch.object(module,'normalize_rows',mutate),self.assertRaises(ValueError):
                read_snapshot(db,root/'output')
            self.assertFalse((root/'output/manifest.json').exists())
            self.assertEqual(json.loads((root/'output/status.json').read_text())['status'],'BLOCKED')


if __name__=='__main__':unittest.main()
