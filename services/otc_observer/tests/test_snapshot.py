import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from services.otc_observer.snapshot import snapshot_database


class SnapshotTests(unittest.TestCase):
    def test_wal_committed_row_merged_without_source_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'live.sqlite';writer=sqlite3.connect(source)
            writer.execute('PRAGMA synchronous=OFF');writer.execute('PRAGMA journal_mode=WAL');writer.execute('CREATE TABLE rows (n INTEGER)')
            writer.execute('INSERT INTO rows VALUES (17)');writer.commit()
            before_main=source.read_bytes(); before_wal=Path(str(source)+'-wal').read_bytes()
            manifest=snapshot_database(source,root/'snapshot.sqlite')
            self.assertEqual(source.read_bytes(),before_main)
            self.assertEqual(Path(str(source)+'-wal').read_bytes(),before_wal)
            con=sqlite3.connect(root/'snapshot.sqlite')
            self.assertEqual(con.execute('select * from rows').fetchall(),[(17,)])
            self.assertEqual(con.execute('pragma journal_mode').fetchone(),('delete',));con.close()
            self.assertTrue(manifest['source_opened_read_only']);self.assertFalse(manifest['source_data_modified'])
            self.assertEqual(manifest['snapshot_sha256'],hashlib.sha256((root/'snapshot.sqlite').read_bytes()).hexdigest())
            with self.assertRaises(ValueError):snapshot_database(source,root/'snapshot.sqlite')
            writer.close()


if __name__=='__main__':unittest.main()
