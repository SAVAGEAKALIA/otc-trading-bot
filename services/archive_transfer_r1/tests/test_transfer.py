import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transfer import Downloader, Invalid, run

URL = 'https://quote-saver.bycsi.com/orderbook/spot/BTCUSDT/2026-10-30_BTCUSDT_ob200.data.zip'

def fixture():
    target = io.BytesIO()
    with zipfile.ZipFile(target, 'w') as z:
        z.writestr('events.data', b'{"event":"test"}\n'*100)
    return target.getvalue()

class Response(io.BytesIO):
    def __init__(self, data, headers, status=206):
        super().__init__(data)
        self.headers, self.status = headers, status

class Fake:
    def __init__(self, data):
        self.data, self.calls, self.mode = data, [], None
        self.tag = '"version1"'
        self.failures = 0
    def __call__(self, url, headers, timeout):
        self.calls.append(dict(headers))
        start, end = map(int, headers['Range'][6:].split('-'))
        if self.failures:
            self.failures -= 1
            raise TimeoutError('synthetic')
        body = self.data[start:end+1]
        h = {'ETag': self.tag, 'Content-Range': f'bytes {start}-{end}/{len(self.data)}', 'Content-Length': str(len(body))}
        status = 206
        if self.mode == 'wrong_range': h['Content-Range'] = 'bytes 1-1/2'
        if self.mode == 'truncate': body = body[:-1]
        if self.mode == 'ignored': status = 200
        if self.mode == 'weak': h['ETag'] = 'W/"version1"'
        if self.mode == 'changed' and 'If-Range' in headers: h['ETag'] = '"version2"'
        if self.mode == 'interrupt' and start >= 128: raise TimeoutError('interrupted')
        return Response(body, h, status)

class TransferTests(unittest.TestCase):
    def setUp(self):
        # Gate tests check atomic visibility; avoid host-dependent disk flush latency.
        flush = patch('transfer.os.fsync')
        flush.start()
        self.addCleanup(flush.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fake = Fake(fixture())
        self.item = {'url': URL, 'size': len(self.fake.data)}
    def downloader(self):
        return Downloader(self.root, workers=1, chunk_bytes=128, attempts=2, opener=self.fake,
                          sleeper=lambda _: None, progress=self.root/'progress.jsonl')
    def test_complete_and_resume_no_chunks_requested(self):
        result = self.downloader().archive(self.item)
        self.assertEqual(Path(result['local_file']).read_bytes(), self.fake.data)
        self.assertTrue(result['zip_crc_verified'])
        self.fake.calls.clear()
        self.downloader().archive(self.item)
        self.assertEqual(len(self.fake.calls), 1)
    def test_every_chunk_uses_if_range(self):
        self.downloader().archive(self.item)
        self.assertTrue(all(c.get('If-Range') == '"version1"' for c in self.fake.calls[1:]))
    def test_invalid_responses_never_promoted(self):
        for mode in ['wrong_range', 'truncate', 'ignored', 'weak', 'changed']:
            with self.subTest(mode=mode):
                self.fake.mode = mode
                with self.assertRaises(Invalid): self.downloader().archive(self.item)
                self.assertFalse(list(self.root.glob('*.zip')))
    def test_timeout_retry(self):
        self.fake.failures = 1
        downloader = self.downloader()
        downloader.archive(self.item)
        self.assertEqual(downloader.errors, 1)
    def test_interruption_resumes_verified_chunks(self):
        self.fake.mode = 'interrupt'
        with self.assertRaises(TimeoutError): self.downloader().archive(self.item)
        self.assertFalse(list(self.root.glob('*.zip')))
        self.assertTrue(list(self.root.glob('*.chunks/0.json')))
        self.fake.mode = None
        self.fake.calls.clear()
        self.downloader().archive(self.item)
        self.assertNotIn('bytes=0-127', [c['Range'] for c in self.fake.calls])
    def test_corrupt_cached_chunk_is_refetched(self):
        self.downloader().archive(self.item)
        next(self.root.glob('*.chunks/0.bin')).write_bytes(b'X'*128)
        self.fake.calls.clear()
        self.downloader().archive(self.item)
        self.assertIn('bytes=0-127', [c['Range'] for c in self.fake.calls])
    def test_changed_identity_on_restart(self):
        self.downloader().archive(self.item)
        self.fake.tag = '"version2"'
        with self.assertRaises(Invalid): self.downloader().archive(self.item)
    def test_bad_zip_never_promoted(self):
        self.fake.data = b'not a zip'*100
        self.item['size'] = len(self.fake.data)
        with self.assertRaises(zipfile.BadZipFile): self.downloader().archive(self.item)
        self.assertFalse(list(self.root.glob('*.zip')))
        self.assertEqual(json.loads((self.root/'progress.jsonl').read_text().splitlines()[-1])['status'], 'failed')
    def test_url_allowlist(self):
        for url in [URL+'?secret=x', URL.replace('https:', 'http:'), URL.replace('quote-saver.bycsi.com', 'evil.test'), URL.replace('BTCUSDT_ob200', 'ETHUSDT_ob200')]:
            with self.subTest(url=url):
                with self.assertRaises(Invalid): self.downloader().archive(dict(self.item, url=url))
        self.assertEqual(self.fake.calls, [])
    def test_duplicate_members_rejected(self):
        import warnings
        stream = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(stream, 'w') as z:
                z.writestr('same', b'bad')
                z.writestr('same', b'good')
        self.fake.data = stream.getvalue()
        self.item['size'] = len(self.fake.data)
        with self.assertRaises(Invalid): self.downloader().archive(self.item)
        self.assertFalse(list(self.root.glob('*.zip')))

    def test_failed_rerun_invalidates_manifest(self):
        run(self.downloader(), [self.item])
        self.fake.mode = 'wrong_range'
        with self.assertRaises(Invalid): run(self.downloader(), [self.item])
        self.assertFalse(json.loads((self.root/'verified_manifest.json').read_text())['full_zip_crc_verified'])
        self.assertEqual(json.loads((self.root/'run_status.json').read_text())['status'], 'failed')
        records = [json.loads(line) for line in (self.root/'progress.jsonl').read_text().splitlines()]
        self.assertEqual(sum(r['status']=='failed' for r in records), 1)

    def test_failure_counts_durable_sibling_receipts(self):
        import threading
        failed = threading.Event()
        def opener(url, headers, timeout):
            if headers['Range'] == 'bytes=0-127':
                failed.set()
                raise Invalid('first range rejected')
            if headers['Range'] == 'bytes=128-255':
                self.assertTrue(failed.wait(1))
            return self.fake(url, headers, timeout)
        downloader = Downloader(self.root, workers=2, chunk_bytes=128, opener=opener,
                                progress=self.root/'progress.jsonl')
        with self.assertRaises(Invalid):
            downloader.archive(self.item)
        receipts = [json.loads(path.read_text()) for path in self.root.glob('*.chunks/[0-9]*.json')]
        verified = sum(row['end'] - row['start'] + 1 for row in receipts)
        terminal = json.loads((self.root/'progress.jsonl').read_text().splitlines()[-1])
        self.assertGreater(verified, 0)
        self.assertEqual(terminal['verified_bytes'], verified)
        self.assertEqual(terminal['percent'], 100 * verified / self.item['size'])

    def test_symlink_rejected(self):
        (self.root/'spot-2026-10-30_BTCUSDT_ob200.data.zip.chunks').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(Invalid): self.downloader().archive(self.item)

if __name__ == '__main__': unittest.main()
