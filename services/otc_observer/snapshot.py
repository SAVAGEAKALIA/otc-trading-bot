"""Create a consistent local SQLite backup from a read-only source, including WAL."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time


def sha256(path, progress=None):
    with path.open('rb') as stream:
        if progress is None:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
        digest = hashlib.sha256(); completed = 0; total = path.stat().st_size
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block); completed += len(block); progress(completed, total)
        return digest.hexdigest()


def file_state(path):
    if not path.exists():
        return {'present': False}
    info = path.stat()
    return {'present': True, 'size_bytes': info.st_size, 'mtime_ns': info.st_mtime_ns,
            'ctime_ns': info.st_ctime_ns}


def snapshot_database(source: Path, destination: Path, *, progress_log: Path | None = None):
    source = source.resolve(strict=True); destination = destination.resolve()
    if destination.exists() or destination == source:
        raise ValueError('Snapshot destination must be a new file')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination.parent).free < source.stat().st_size + 1024 * 1024:
        raise ValueError('Insufficient free space for consistent SQLite snapshot')
    progress_log = progress_log or destination.parent / 'progress.log'
    input_state = {str(source): file_state(source),
                   str(source) + '-wal': file_state(Path(str(source) + '-wal')),
                   str(source) + '-shm': file_state(Path(str(source) + '-shm'))}
    start = time.monotonic(); last_report = -float('inf')
    with progress_log.open('a') as stream:
        def phase(name, **values):
            item = {'event': 'OTC SQLite snapshot', 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                    'phase': name, 'percent': None, 'eta_seconds': None, **values}
            line = json.dumps(item, sort_keys=True, allow_nan=False)
            print(line, flush=True); stream.write(line + '\n'); stream.flush()
        def progress(status, remaining, total):
            nonlocal last_report
            elapsed = time.monotonic() - start
            if elapsed - last_report < 5 and remaining:
                return
            copied = total - remaining
            rate = copied / elapsed if elapsed and copied else 0
            item = {'event': 'OTC SQLite snapshot', 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                    'phase': 'copying_pages',
                    'pages_copied': copied, 'pages_total': total,
                    'percent': round(100 * copied / total, 2) if total else 0,
                    'eta_seconds': round(remaining / rate, 2) if rate else None,
                    'sqlite_status': status}
            line = json.dumps(item, sort_keys=True, allow_nan=False)
            print(line, flush=True); stream.write(line + '\n'); stream.flush(); last_report = elapsed
        origin = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
        target = sqlite3.connect(destination)
        try:
            origin.execute('PRAGMA query_only=ON')
            origin.execute('BEGIN')
            origin.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()
            origin.backup(target, pages=512, progress=progress)
            # The offline output must not depend on an external WAL file.
            target.execute('PRAGMA journal_mode=DELETE').fetchone()
            phase('quick_check')
            last_check_report = time.monotonic(); check_steps = 0
            def checking():
                nonlocal last_check_report, check_steps
                check_steps += 100000
                now = time.monotonic()
                if now - last_check_report >= 15:
                    phase('quick_check', sqlite_vm_steps=check_steps)
                    last_check_report = now
                return 0
            target.set_progress_handler(checking, 100000)
            if target.execute('PRAGMA quick_check').fetchone() != ('ok',):
                raise ValueError('SQLite snapshot quick_check failed')
            target.set_progress_handler(None, 0)
            phase('quick_check_complete')
            target.commit()
        finally:
            origin.rollback(); origin.close(); target.close()
    with progress_log.open('a') as stream:
        last_hash_report = -float('inf')
        def hashing(completed, total):
            nonlocal last_hash_report
            now = time.monotonic()
            if now - last_hash_report < 15 and completed != total:
                return
            item = {'event': 'OTC SQLite snapshot', 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                    'phase': 'hashing', 'bytes_hashed': completed, 'bytes_total': total,
                    'percent': round(100 * completed / total, 2), 'eta_seconds': None}
            line = json.dumps(item, sort_keys=True);print(line, flush=True);stream.write(line + '\n');stream.flush();last_hash_report = now
        digest = sha256(destination, progress=hashing)
    manifest = {'schema': 'otc_sqlite_snapshot_v1', 'source_path': str(source),
                'source_file_state_before': input_state,
                'snapshot_path': str(destination), 'snapshot_sha256': digest,
                'snapshot_size_bytes': destination.stat().st_size,
                'snapshot_basis': 'SQLite online backup from one read transaction; committed WAL pages merged',
                'source_opened_read_only': True, 'source_data_modified': False,
                'snapshot_journal_mode': 'delete', 'quick_check': 'ok'}
    destination.with_suffix(destination.suffix + '.manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--progress-log', type=Path)
    args = parser.parse_args(); snapshot_database(args.source, args.destination, progress_log=args.progress_log)


if __name__ == '__main__':
    main()
