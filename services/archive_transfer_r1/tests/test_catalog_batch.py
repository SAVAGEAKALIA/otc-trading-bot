from datetime import date
from pathlib import Path
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transfer import Downloader, Invalid, catalog_batch, check_batch_space, run

CATALOG = Path(__file__).resolve().parents[3] / 'docs/research/crypto-r1-2026-10-31/depth_catalog_inventory.csv'
DAY = date(2026, 8, 2)


class CatalogTests(unittest.TestCase):
    def test_complete_day_and_legacy_rejection(self):
        items = catalog_batch(CATALOG, DAY, DAY)
        self.assertEqual(len(items), 4)
        with tempfile.TemporaryDirectory() as output:
            with self.assertRaises(Invalid):
                Downloader(output).archive(items[0])
            with self.assertRaisesRegex(Invalid, '1 MiB'):
                Downloader(output, catalog_items=items, chunk_bytes=1)
            pinned = Downloader(output, catalog_items=items)
            with self.assertRaises(Invalid):
                pinned.archive(dict(items[0], size='1'))

    def test_reject_window_and_tampering(self):
        for start, end in ((DAY, date(2026, 8, 9)), (date(2026, 8, 1), DAY), (DAY, date(2026, 8, 1))):
            with self.assertRaises(Invalid):
                catalog_batch(CATALOG, start, end)
        with tempfile.TemporaryDirectory() as output:
            changed = Path(output) / 'inventory.csv'
            changed.write_bytes(CATALOG.read_bytes() + b'\n')
            with self.assertRaisesRegex(Invalid, 'SHA-256'):
                catalog_batch(changed, DAY, DAY)

    def test_storage_preflight_boundary(self):
        items = catalog_batch(CATALOG, DAY, DAY)
        needed = 2 * sum(int(item['size']) for item in items) + 1024**3
        with patch('transfer.shutil.disk_usage', return_value=SimpleNamespace(free=needed)):
            self.assertEqual(check_batch_space('.', items), needed)
        with patch('transfer.shutil.disk_usage', return_value=SimpleNamespace(free=needed - 1)):
            with self.assertRaises(Invalid):
                check_batch_space('.', items)

    def test_low_space_blocks_run_before_network(self):
        items = catalog_batch(CATALOG, DAY, DAY)
        with tempfile.TemporaryDirectory() as output:
            def forbidden(*args):
                self.fail('network opened before storage preflight')
            downloader = Downloader(output, catalog_items=items, opener=forbidden)
            manifest = Path(output) / 'verified_manifest.json'
            manifest.write_text(json.dumps({'status': 'complete', 'full_zip_crc_verified': True}))
            with patch('transfer.shutil.disk_usage', return_value=SimpleNamespace(free=0)):
                with self.assertRaisesRegex(Invalid, 'free bytes'):
                    run(downloader, items)
            self.assertEqual(json.loads(manifest.read_text())['status'], 'failed')
