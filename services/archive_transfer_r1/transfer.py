"""Pinned public archive range transfer; Python standard library only."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import closing
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile

URL = re.compile(r'https://quote-saver\.bycsi\.com/orderbook/(spot|linear)/(BTCUSDT|ETHUSDT)/2026-10-30_\2_ob200\.data\.zip\Z')

class Invalid(Exception):
    """Evidence or response violates the archive contract."""

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Invalid('redirect forbidden')

def _read_range_child():
    """Bound stdout to the requested range plus a short metadata record."""
    url, headers, timeout = json.load(sys.stdin)
    match = re.fullmatch(r'bytes=(\d+)-(\d+)', headers['Range'])
    limit = int(match[2]) - int(match[1]) + 2
    if not 1 < limit <= 16 * 1024 * 1024 + 1:
        raise Invalid('invalid child range size')
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            metadata = {
                'status': response.status,
                'headers': {key: response.headers[key] for key in
                            ('ETag', 'Content-Range', 'Content-Length', 'Content-Encoding')
                            if key in response.headers},
            }
            body = response.read(limit)
    except urllib.error.HTTPError as exc:
        metadata, body = {'http_error': exc.code}, b''
    except (OSError, urllib.error.URLError) as exc:
        metadata, body = {'network_error': str(exc)}, b''
    sys.stdout.buffer.write(json.dumps(metadata).encode() + b'\n' + body)


def transport(url, headers, timeout):
    """Kill the range reader if the complete request exceeds its deadline."""
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), '--range-reader'],
            input=json.dumps([url, headers, timeout]).encode(),
            capture_output=True, timeout=2 * timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError('whole range deadline exceeded') from exc
    if result.returncode:
        raise Invalid('range reader failed')
    raw_metadata, separator, body = result.stdout.partition(b'\n')
    if not separator:
        raise Invalid('missing range metadata')
    metadata = json.loads(raw_metadata)
    if 'http_error' in metadata:
        raise urllib.error.HTTPError(url, metadata['http_error'], 'range request failed', {}, None)
    if 'network_error' in metadata:
        raise OSError(metadata['network_error'])
    response = io.BytesIO(body)
    response.status = metadata['status']
    response.headers = metadata['headers']
    return response


def atomic(path, data):
    if path.is_symlink():
        raise Invalid('symlink forbidden: ' + str(path))
    fd, temporary = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def save(path, value):
    atomic(path, json.dumps(value, sort_keys=True).encode())

def digest(data):
    return hashlib.sha256(data).hexdigest()

def safe_dir(path):
    for node in (path, *path.parents):
        if node.is_symlink():
            raise Invalid('symlink directory forbidden')
    path.mkdir(parents=True, exist_ok=True)

def load(path):
    if path.is_symlink():
        raise Invalid('symlink forbidden')
    return json.loads(path.read_text())

class Downloader:
    def __init__(self, output, *, workers=8, chunk_bytes=1048576, timeout=20, attempts=4,
                 opener=transport, progress=None, sleeper=time.sleep):
        if not 1 <= workers <= 32 or not 1 <= chunk_bytes <= 16*1024*1024 or not 0 < timeout <= 300 or not 1 <= attempts <= 10:
            raise ValueError('invalid transfer bounds')
        self.output = Path(output).absolute()
        self.workers, self.chunk_bytes = workers, chunk_bytes
        self.timeout, self.attempts, self.opener = timeout, attempts, opener
        self.progress, self.sleeper = Path(progress) if progress else None, sleeper
        self.errors = 0
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.network_bytes = 0
        self.last_verified = {}
        safe_dir(self.output)

    def emit(self, **fields):
        with self.lock:
            elapsed = time.monotonic()-self.started
            rate = self.network_bytes/elapsed if elapsed else 0
            remaining = fields.get('total_bytes', 0)-fields.get('verified_bytes', 0)
            record = dict(event='R1 archive transfer', timestamp=time.time(), elapsed_seconds=elapsed,
                          bytes_per_second=rate, eta_seconds=remaining/rate if rate else None,
                          errors=self.errors, **fields)
            if self.progress:
                self.progress.parent.mkdir(parents=True, exist_ok=True)
                if self.progress.is_symlink():
                    raise Invalid('progress symlink forbidden')
                with self.progress.open('a') as stream:
                    stream.write(json.dumps(record)+'\n')
                    stream.flush()
            return record

    def fetch(self, url, start, end, size, tag=None):
        headers = {'Range': f'bytes={start}-{end}', 'Accept-Encoding': 'identity'}
        if tag:
            headers['If-Range'] = tag
        for attempt in range(self.attempts):
            try:
                began = time.monotonic()
                with closing(self.opener(url, headers, self.timeout)) as response:
                    h = response.headers
                    etag = h.get('ETag', '')
                    if not re.fullmatch(r'"[\x21\x23-\x7e\x80-\xff]*"', etag):
                        raise Invalid('strong ETag required')
                    if tag is not None and etag != tag:
                        raise Invalid('remote ETag changed')
                    if response.status != 206 or h.get('Content-Range') != f'bytes {start}-{end}/{size}':
                        raise Invalid('exact 206 range/total required')
                    if h.get('Content-Encoding', 'identity') != 'identity':
                        raise Invalid('encoded range forbidden')
                    expected = end-start+1
                    if h.get('Content-Length') != str(expected):
                        raise Invalid('wrong Content-Length')
                    chunks, count = [], 0
                    while count <= expected:
                        if time.monotonic()-began > self.timeout*2:
                            raise TimeoutError('range deadline exceeded')
                        read = getattr(response, 'read1', response.read)
                        data = read(min(65536, expected+1-count))
                        if not data:
                            break
                        count += len(data)
                        chunks.append(data)
                    if count != expected:
                        raise Invalid('truncated or oversized range')
                    with self.lock:
                        self.network_bytes += count
                    return b''.join(chunks), etag
            except Invalid:
                with self.lock:
                    self.errors += 1
                raise
            except (TimeoutError, OSError, urllib.error.URLError) as exc:
                with self.lock:
                    self.errors += 1
                if isinstance(exc, urllib.error.HTTPError) and exc.code not in (408, 429, 500, 502, 503, 504):
                    raise
                if attempt+1 == self.attempts:
                    raise
                self.sleeper(min(2**attempt, 8))

    def archive(self, item):
        url = item['url']
        match = URL.fullmatch(url)
        if not match:
            raise Invalid('URL outside fixed allowlist')
        size = int(item['size'])
        if not 0 < size <= 2**40:
            raise Invalid('invalid size')
        name = f'{match[1]}-2026-10-30_{match[2]}_ob200.data.zip'
        work = self.output/(name+'.chunks')
        safe_dir(work)
        lockpath = work/'lock'
        if lockpath.is_symlink():
            raise Invalid('lock symlink forbidden')
        with lockpath.open('a') as locked:
            fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.last_verified[name] = 0
            try:
                return self._archive(url, size, name, work)
            except BaseException as exc:
                count = self.last_verified.get(name, 0)
                self.emit(archive=name, status='failed', failure_type=type(exc).__name__,
                          total_bytes=size, verified_bytes=count, percent=100*count/size)
                raise

    def _archive(self, url, size, name, work):
        _, tag = self.fetch(url, 0, 0, size)
        identity = dict(version=1, url=url, size=size, etag=tag, chunk_bytes=self.chunk_bytes)
        meta = work/'identity.json'
        if meta.exists() and load(meta) != identity:
            raise Invalid('checkpoint identity differs; use a fresh output directory')
        save(meta, identity)
        verified, pending = {}, []
        for start in range(0, size, self.chunk_bytes):
            end = min(start+self.chunk_bytes, size)-1
            path, receipt = work/f'{start}.bin', work/f'{start}.json'
            if path.is_symlink() or receipt.is_symlink():
                raise Invalid('chunk symlink forbidden')
            valid = False
            if path.exists() and receipt.exists():
                try:
                    evidence = load(receipt)
                    # Check file size before reading to preserve the memory bound.
                    if path.stat().st_size == end-start+1:
                        data = path.read_bytes()
                        valid = evidence == dict(start=start, end=end, sha256=digest(data), etag=tag)
                except (ValueError, OSError):
                    pass
            if valid:
                verified[start] = end-start+1
            else:
                pending.append((start, end))
        self.last_verified[name] = sum(verified.values())

        def report(status):
            with self.lock:
                count = self.last_verified[name]
            return self.emit(archive=name, status=status, verified_bytes=count, total_bytes=size,
                             percent=100*count/size)
        def download(pair):
            start, end = pair
            data, _ = self.fetch(url, start, end, size, tag)
            atomic(work/f'{start}.bin', data)
            save(work/f'{start}.json', dict(start=start, end=end, sha256=digest(data), etag=tag))
            with self.lock:
                self.last_verified[name] += len(data)
            return start, len(data)
        report('downloading')
        try:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                iterator = iter(pending)
                active = set()
                for _ in range(self.workers):
                    pair = next(iterator, None)
                    if pair is not None:
                        active.add(pool.submit(download, pair))
                while active:
                    done, active = wait(active, return_when=FIRST_COMPLETED)
                    for future in done:
                        start, length = future.result()
                        verified[start] = length
                        report('downloading')
                        pair = next(iterator, None)
                        if pair is not None:
                            active.add(pool.submit(download, pair))
            assembled = self.output/(name+'.assembling')
            final = self.output/name
            if assembled.is_symlink() or final.is_symlink():
                raise Invalid('final symlink forbidden')
            total_hash = hashlib.sha256()
            with assembled.open('wb') as stream:
                for start in range(0, size, self.chunk_bytes):
                    data = (work/f'{start}.bin').read_bytes()
                    if digest(data) != load(work/f'{start}.json')['sha256']:
                        raise Invalid('chunk changed during assembly')
                    stream.write(data)
                    total_hash.update(data)
                stream.flush()
                os.fsync(stream.fileno())
            if assembled.stat().st_size != size:
                raise Invalid('assembled size mismatch')
            with zipfile.ZipFile(assembled) as archive:
                members = archive.infolist()
                if len(members) != 1 or members[0].is_dir():
                    raise Invalid('exactly one non-directory ZIP member required')
                member = members[0]
                if member.file_size > 128 * 1024**3:
                    raise Invalid('ZIP member exceeds 128 GiB limit')
                actual = 0
                with archive.open(member) as content:
                    while True:
                        block = content.read(1024*1024)
                        if not block:
                            break
                        actual += len(block)
                        if actual > member.file_size or actual > 128 * 1024**3:
                            raise Invalid('ZIP expanded size exceeded')
                if actual != member.file_size:
                    raise Invalid('ZIP expanded size mismatch')
            os.replace(assembled, final)
            directory = os.open(self.output, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            result = dict(**identity, local_file=str(final), sha256=total_hash.hexdigest(), zip_crc_verified=True)
            save(self.output/(name+'.verified.json'), result)
            report('complete')
            return result
        except BaseException:
            raise

def run(downloader, items):
    """One run owns status and invalidates previous completion before any network IO."""
    output = downloader.output
    lockpath = output/'run.lock'
    if lockpath.is_symlink():
        raise Invalid('run lock symlink forbidden')
    with lockpath.open('a') as locked:
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = output/'verified_manifest.json'
        # Atomic tombstone avoids an old success surviving a failed rerun.
        save(manifest, dict(files=[], full_zip_crc_verified=False, status='running'))
        save(output/'run_status.json', dict(status='running'))
        try:
            results = [downloader.archive(item) for item in items]
            save(manifest, dict(files=results, status='complete', full_zip_crc_verified=True,
                                full_day_replay_completed=False))
            save(output/'run_status.json', dict(status='complete'))
            return results
        except BaseException as exc:
            save(manifest, dict(files=[], status='failed', full_zip_crc_verified=False))
            save(output/'run_status.json', dict(status='failed', failure_type=type(exc).__name__))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--progress', required=True, type=Path)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--chunk-bytes', type=int, default=1048576)
    args = parser.parse_args()
    items = load(args.manifest)['files']
    urls = [item['url'] for item in items]
    if len(items) != 4 or len(set(urls)) != 4 or any(not URL.fullmatch(url) for url in urls):
        parser.error('manifest must contain the four unique allowlisted archives')
    downloader = Downloader(args.output, workers=args.workers, chunk_bytes=args.chunk_bytes, progress=args.progress)
    run(downloader, items)

if __name__ == '__main__':
    if sys.argv[1:] == ['--range-reader']:
        _read_range_child()
    else:
        main()
