"""Owned-process daily segmentation and verified lossless archival. Python 3.10 stdlib."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import threading
import time

DAY_MS = 86_400_000
HANDOFF_OFFSET_MS = 90_000
STARTUP_GRACE_SECONDS = 15
SUMMARY_COLUMNS = {"registration": {"singleton", "record_json"}, "sessions": {"session_id", "transition", "at_ms"},
                   "receipts": {"frame_id", "received_at_ms"}, "observations": {"asset", "kind", "available_ms"},
                   "health": {"code"}}
CHUNK = 1_048_576
COLLECTOR_PYTHON = '/usr/bin/python3'
TRANSPORT_FATAL = frozenset({"reconnect_budget_exhausted", "network_close_timeout"})
DENY_RESTART = frozenset({"receiver_clock_jump", "broker_clock_offset", "clock_sync_stale",
                         "authentication_ack_timeout", "authentication_failed", "authentication_transport_failed",
                         "transport_or_storage_halted", "storage_write_failure", "storage_open_failure",
                         "queue_overflow", "writer_internal_error", "writer_close_timeout", "outside_registered_window"})


class OpsFault(RuntimeError):
    """Safe fixed diagnostics only, never raw subprocess/broker error text."""


def failure_code(error, *, archive=False, raw_removed=False):
    """Classify operational exceptions without persisting their possibly private text."""
    if isinstance(error, OpsFault):
        return str(error)
    if archive:
        suffix = "post_removal" if raw_removed else "raw_retained"
        return f"archive_{'io_failed' if isinstance(error, (OSError, sqlite3.Error)) else 'unexpected_failure'}_{suffix}"
    return "supervisor_operational_io_failed" if isinstance(error, (OSError, sqlite3.Error)) else "supervisor_unexpected_failure"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def utc_ms():
    return time.time_ns() // 1_000_000


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def integer(value, code):
    if type(value) is not int or value < 0:
        raise OpsFault(code)
    return value


def safe_path(value, namespace):
    path = Path(value).resolve()
    if not path.is_relative_to(Path(namespace).resolve()):
        raise OpsFault("path_outside_owned_namespace")
    return path


def read_registration(path):
    record = json.loads(Path(path).read_text())
    if not isinstance(record, dict):
        raise OpsFault("invalid_registration")
    lock = record.get("registration_sha256")
    content = dict(record)
    content.pop("registration_sha256", None)
    if not isinstance(lock, str) or lock != digest(content):
        raise OpsFault("registration_hash_mismatch")
    start, end = integer(record.get("start_ms"), "invalid_start"), integer(record.get("end_ms"), "invalid_end")
    created = record.get("created_ms", record.get("registered_at_ms"))
    if integer(created, "invalid_created") >= start or start % 120_000 or end - start != 7 * DAY_MS:
        raise OpsFault("registration_chronology_mismatch")
    if record.get("assets") != ["EURUSD-OTC", "GBPUSD-OTC"] or record.get("product") != "turbo-option":
        raise OpsFault("registration_scope_mismatch")
    return record


def handoff_boundaries(record):
    return [record["start_ms"] + day * DAY_MS + HANDOFF_OFFSET_MS for day in range(1, 7)] + [record["end_ms"]]


def verify_source(source_root, registration):
    base = Path(source_root).resolve() / "services" / "otc_collector"
    expected = registration.get("code_files")
    if not isinstance(expected, dict) or not expected:
        raise OpsFault("missing_frozen_collector_hashes")
    actual = {}
    for directory, subdirs, names in os.walk(base):
        subdirs[:] = sorted(name for name in subdirs if name != "__pycache__")
        for name in sorted(names):
            if name.endswith(".py"):
                path = Path(directory) / name
                actual[str(path.relative_to(base))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected or digest(actual) != registration.get("code_sha256"):
        raise OpsFault("immutable_collector_source_changed")
    return actual


def option(argv, name):
    found = []
    for index, arg in enumerate(argv):
        if arg == name and index + 1 < len(argv):
            found.append(argv[index + 1])
        elif arg.startswith(name + "="):
            found.append(arg[len(name) + 1:])
    if len(found) != 1:
        raise OpsFault("missing_or_duplicate_process_option")
    return found[0]


def validate_launch_template(argv):
    """Only the existing collector CLI is retained; credentials are file paths, never values."""
    if not isinstance(argv, list) or not all(isinstance(value, str) for value in argv):
        raise OpsFault('process_module_mismatch')
    if argv[:2] == [COLLECTOR_PYTHON, '-m']:
        module = 1
    elif argv[:3] == [COLLECTOR_PYTHON, '-u', '-m']:
        module = 2
    else:
        raise OpsFault('process_interpreter_or_prefix_mismatch')
    if argv[module + 1:module + 3] != ["services.otc_collector.runner", "live"]:
        raise OpsFault("process_module_mismatch")
    known = {"--registration", "--db", "--env-file", "--progress-log"}
    seen, index = set(), module + 3
    while index < len(argv):
        arg = argv[index]
        if arg == "--allow-account-read":
            if arg in seen:
                raise OpsFault("duplicate_process_argument")
            seen.add(arg)
            index += 1
            continue
        key = arg.partition("=")[0]
        if key not in known or key in seen:
            raise OpsFault("unexpected_or_duplicate_process_argument")
        value = option(argv, key)
        if not Path(value).is_absolute():
            raise OpsFault("collector_argument_path_not_absolute")
        seen.add(key)
        index += 1 if "=" in arg else 2
    if not {"--registration", "--db", "--env-file", "--allow-account-read"}.issubset(seen):
        raise OpsFault("collector_launch_argument_missing")
    return argv


def process_identity(pid, database, registration, source_root, *, proc_root="/proc", expected_start=None):
    """Validate argv, cwd and Linux start ticks without reading process environment."""
    integer(pid, "invalid_pid")
    if pid <= 1:
        raise OpsFault("invalid_pid")
    proc = Path(proc_root) / str(pid)
    try:
        argv = [value.decode("utf-8") for value in (proc / "cmdline").read_bytes().split(b"\0") if value]
        stat = (proc / "stat").read_text()
        start = int(stat[stat.rfind(")") + 2:].split()[19])
        cwd = (proc / "cwd").resolve(strict=True)
        executable = (proc / 'exe').resolve(strict=True)
    except (OSError, ValueError, UnicodeError, IndexError):
        raise OpsFault("owned_process_not_found") from None
    if expected_start is not None and start != expected_start:
        raise OpsFault("pid_reused")
    try:
        module_index = argv.index("-m")
    except ValueError:
        raise OpsFault("process_module_mismatch") from None
    if argv[module_index + 1:module_index + 3] != ["services.otc_collector.runner", "live"]:
        raise OpsFault("process_module_mismatch")
    validate_launch_template(argv)
    if executable != Path(COLLECTOR_PYTHON).resolve(strict=True):
        raise OpsFault('process_executable_mismatch')
    if Path(option(argv, "--db")).resolve() != Path(database).resolve() or Path(option(argv, "--registration")).resolve() != Path(registration).resolve():
        raise OpsFault("process_database_registration_mismatch")
    if cwd != Path(source_root).resolve() or "--allow-account-read" not in argv:
        raise OpsFault("process_source_or_ack_mismatch")
    return {"pid": pid, "start_ticks": start, "argv": argv}


def alive(pid, start_ticks, *, proc_root="/proc"):
    try:
        stat = (Path(proc_root) / str(pid) / "stat").read_text()
        fields = stat[stat.rfind(")") + 2:].split()
        return fields[0] != "Z" and int(fields[19]) == start_ticks
    except FileNotFoundError:
        if not Path(proc_root).is_dir():
            raise OpsFault("owned_process_liveness_read_failed") from None
        return False
    except (OSError, ValueError, IndexError):
        raise OpsFault("owned_process_liveness_read_failed") from None


def database_summary(database, registration_id, *, checkpoint=False, allow_startup=False):
    path = Path(database).resolve()
    if not path.is_file():
        raise OpsFault("segment_database_missing")
    conn = None
    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        objects = list(conn.execute("SELECT name,type FROM sqlite_master"))
        names = {name for name, kind in objects if kind == "table"}
        if allow_startup and not checkpoint:
            if not objects:
                return {"read_status": "awaiting_owned_database_startup"}
        if names != set(SUMMARY_COLUMNS) or any(
                kind == "view" for _, kind in objects):
            raise OpsFault("segment_database_schema_mismatch")
        if any(not required.issubset({row[1] for row in conn.execute(f"PRAGMA table_info({table})")})
               for table, required in SUMMARY_COLUMNS.items()):
            raise OpsFault("segment_database_schema_mismatch")
        row = conn.execute("SELECT record_json FROM registration WHERE singleton=1").fetchone()
        if allow_startup and not checkpoint and row is None:
            if names == {"registration", "sessions", "receipts", "observations", "health"} and all(
                    conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0 for table in sorted(names)):
                return {"read_status": "awaiting_owned_database_startup"}
        stored = json.loads(row[0]) if row is not None else {}
        stored_content = dict(stored)
        stored_content.pop("registration_sha256", None)
        if stored.get("registration_sha256") != registration_id or digest(stored_content) != registration_id:
            raise OpsFault("segment_registration_mismatch")
        # Registration is proved before any writable checkpoint. Foreign
        # SQLite/WAL bytes must remain untouched when identity is rejected.
        if checkpoint:
            conn.close()
            conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5)
            result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if result[0] != 0 or result[1] != result[2]:
                raise OpsFault("closed_database_checkpoint_busy")
        sessions = conn.execute("SELECT count(*) FROM sessions WHERE transition='open'").fetchone()[0]
        closed = conn.execute("SELECT count(*) FROM sessions WHERE transition='close'").fetchone()[0]
        unclosed = conn.execute("SELECT count(*) FROM sessions s WHERE s.transition='open' AND NOT EXISTS(SELECT 1 FROM sessions c WHERE c.session_id=s.session_id AND c.transition='close')").fetchone()[0]
        first, last = conn.execute("SELECT min(received_at_ms),max(received_at_ms) FROM receipts").fetchone()
        counts = dict(conn.execute("SELECT kind,count(*) FROM observations GROUP BY kind"))
        health = dict(conn.execute("SELECT code,count(*) FROM health GROUP BY code"))
        last_health = conn.execute("SELECT code FROM health ORDER BY rowid DESC LIMIT 1").fetchone()
        latest_close_code = None
        if "detail_json" in {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}:
            close_row = conn.execute("SELECT detail_json FROM sessions WHERE transition='close' ORDER BY at_ms DESC,rowid DESC LIMIT 1").fetchone()
            if close_row is not None:
                latest_close_code = json.loads(close_row[0]).get("code")
        latest = dict(conn.execute("SELECT asset,max(available_ms) FROM observations WHERE kind='quote' GROUP BY asset"))
        return {"session_count": sessions, "closed_session_count": closed, "unclosed_session_count": unclosed,
                "first_receipt_ms": first, "last_receipt_ms": last, "observation_counts": counts,
                "receipt_count": conn.execute("SELECT count(*) FROM receipts").fetchone()[0],
                "health_counts": health, "latest_health_code": last_health[0] if last_health else None,
                "latest_close_code": latest_close_code,
                "latest_quote_receipts_ms": latest}
    except (sqlite3.Error, ValueError, TypeError):
        raise OpsFault("segment_database_read_failed") from None
    finally:
        if conn is not None:
            conn.close()


def restart_allowed(summary):
    health = set(summary["health_counts"])
    reason = summary.get("latest_close_code") or summary["latest_health_code"]
    return reason in TRANSPORT_FATAL and not health.intersection(DENY_RESTART)


def sha_file(path):
    checksum, size = hashlib.sha256(), 0
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            checksum.update(chunk)
            size += len(chunk)
    return checksum.hexdigest(), size


def verify_gzip(path, expected_sha, expected_bytes):
    checksum, size = hashlib.sha256(), 0
    try:
        with gzip.open(path, "rb") as handle:
            while True:
                chunk = handle.read(CHUNK)
                if not chunk:
                    break
                checksum.update(chunk)
                size += len(chunk)
    except (OSError, EOFError):
        raise OpsFault("gzip_verification_failed") from None
    if checksum.hexdigest() != expected_sha or size != expected_bytes:
        raise OpsFault("gzip_raw_hash_mismatch")
    return checksum.hexdigest(), size


@contextmanager
def closed_raw_lease(path):
    """Reuse the immutable collector's own writer lock during archive/removal."""
    with Path(str(path) + ".lock").open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise OpsFault("raw_database_writer_lock_busy") from None
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def archive_closed(segment, namespace, registration_id, *, remove_raw=True):
    """Compress only a manifested owned closed scratch DB, then verify before unlink."""
    if segment.get("state") != "producer_closed" or segment.get("registration_sha256") != registration_id or segment.get("owned") is not True:
        raise OpsFault("archive_ownership_or_closure_missing")
    raw = safe_path(segment["db_path"], namespace)
    with closed_raw_lease(raw):
        return _archive_closed(segment, namespace, registration_id, remove_raw=remove_raw)


def _archive_closed(segment, namespace, registration_id, *, remove_raw):
    raw = safe_path(segment["db_path"], namespace)
    archive = safe_path(segment.get("gzip_target", str(raw) + ".gz"), namespace)
    archive.parent.mkdir(parents=True, exist_ok=True)
    partial = safe_path(str(archive) + ".partial", namespace)
    summary = database_summary(raw, registration_id, checkpoint=True)
    if summary["unclosed_session_count"] and segment.get("close_reason") != "verified_transport_crash":
        raise OpsFault("collector_sessions_not_closed")
    before = raw.stat()
    checksum, raw_bytes = hashlib.sha256(), 0
    try:
        if archive.exists() or partial.exists():
            raw_sha, raw_bytes = sha_file(raw)
            retained = archive if archive.exists() else partial
            verify_gzip(retained, raw_sha, raw_bytes)
            gzip_sha, gzip_bytes = sha_file(retained)
            with retained.open("rb") as durable:
                os.fsync(durable.fileno())
        else:
            with raw.open("rb") as source, partial.open("xb") as target:
                with gzip.GzipFile(filename="", mode="wb", fileobj=target, compresslevel=6, mtime=0) as compressed:
                    while True:
                        chunk = source.read(CHUNK)
                        if not chunk:
                            break
                        checksum.update(chunk)
                        raw_bytes += len(chunk)
                        compressed.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            raw_sha = checksum.hexdigest()
            verify_gzip(partial, raw_sha, raw_bytes)
            gzip_sha, gzip_bytes = sha_file(partial)
        after = raw.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise OpsFault("closed_raw_database_changed")
        if not archive.exists():
            os.replace(partial, archive)
        dir_fd = os.open(str(archive.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        result = {**summary, "gzip_path": str(archive), "raw_sha256": raw_sha, "raw_bytes": raw_bytes,
                  "gzip_sha256": gzip_sha, "gzip_bytes": gzip_bytes, "compressed_at_ms": utc_ms(),
                  "lossless_verified": True, "raw_removed": False}
        # Recheck exact bytes before deletion; any intervening change keeps raw data.
        if remove_raw:
            if sha_file(raw) != (raw_sha, raw_bytes):
                raise OpsFault("raw_changed_before_removal")
            raw.unlink()
            result["raw_removed"] = True
        return result
    except OpsFault:
        raise
    except OSError:
        raise OpsFault("archive_io_failed_raw_retained") from None


def atomic_json(path, record):
    path = Path(path)
    partial = path.with_name(path.name + ".next")
    with partial.open("w", encoding="utf-8") as handle:
        handle.write(canonical(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)
    directory = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def source_chain(state):
    """Exact public contract. All operational details stay in ops-state.json."""
    segments = []
    for segment in sorted(state["segments"], key=lambda item: item["ordinal"]):
        if segment.get("state") == "archive_verified":
            segments.append({"path": segment["gzip_path"], "compressed_sha256": segment["gzip_sha256"],
                             "sqlite_sha256": segment["raw_sha256"], "sqlite_bytes": segment["raw_bytes"],
                             "closed_at_ms": segment["closed_at_ms"]})
        else:
            break  # Never publish a later archive ahead of an earlier pending segment.
    return {"schema": "fresh_otc_source_chain_v1", "registration_sha256": state["registration_sha256"],
            "complete": state["complete"] is True, "segments": segments}


class Supervisor:
    def __init__(self, args):
        self.args = args
        self.namespace = Path(args.namespace).resolve()
        if not self.namespace.is_relative_to(Path("/tmp")):
            raise OpsFault("namespace_must_be_scratch_tmp")
        self.namespace.mkdir(parents=True, exist_ok=True)
        self.registration_path = Path(args.registration).resolve()
        self.registration = read_registration(self.registration_path)
        self.source = Path(args.source).resolve()
        verify_source(self.source, self.registration)
        self.source_registration_bytes_sha256 = sha_file(self.registration_path)[0]
        self.registration_id = self.registration["registration_sha256"]
        self.chain_path = self.namespace / "sourcechain.json"
        self.state_path = self.namespace / "ops-state.json"
        self.progress_path = safe_path(args.progress_log, self.namespace)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="closed-otc-gzip")
        self.archives = []
        self.active = None
        self.argv = None
        self.children = {}
        self.startup_deadlines = {}
        self.failure = None
        self.process_lock = (self.namespace / "collection-ops.lock").open("a")
        try:
            fcntl.flock(self.process_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise OpsFault("another_supervisor_owns_namespace") from None
        try:
            self.initialize_state(args)
        except Exception as error:
            # Adoption can fail saving state after positively identifying a live
            # producer, before main() receives this instance. Close it here too.
            if self.active is not None:
                self.fail_closed(error)
            try:
                self.executor.shutdown(wait=True)
            finally:
                self.process_lock.close()
            raise OpsFault(self.failure or failure_code(error)) from None

    def initialize_state(self, args):
        if self.state_path.exists():
            self.restore()
            return
        if self.chain_path.exists():
            raise OpsFault("public_chain_without_owned_ops_state")
        self.chain = {"schema": "otc_collection_ops_state_v1", "registration_sha256": self.registration_id,
                      "registration_path": str(self.registration_path), "registration_file_sha256": self.source_registration_bytes_sha256,
                      "source_root": str(self.source), "collector_code_sha256": self.registration["code_sha256"],
                      "global_start_ms": self.registration["start_ms"], "global_end_ms": self.registration["end_ms"],
                      "global_start_utc": iso(self.registration["start_ms"]), "global_end_utc": iso(self.registration["end_ms"]),
                      "canonical_initial_db": str(safe_path(args.initial_db, self.namespace)),
                      "handoff_boundaries_ms": handoff_boundaries(self.registration), "segments": [],
                      "events": [], "complete": False, "transport_restart_count": 0,
                      "supervisor_source_sha256": sha_file(__file__)[0], "created_at_ms": utc_ms()}
        self.adopt(args.adopt_pid, args.initial_db)

    def restore(self):
        self.chain = json.loads(self.state_path.read_text())
        if (self.chain.get("schema") != "otc_collection_ops_state_v1" or self.chain.get("registration_sha256") != self.registration_id
                or self.chain.get("registration_file_sha256") != self.source_registration_bytes_sha256
                or self.chain.get("source_root") != str(self.source)
                or self.chain.get("global_start_ms") != self.registration["start_ms"]
                or self.chain.get("global_end_ms") != self.registration["end_ms"]
                or self.chain.get("canonical_initial_db") != str(safe_path(self.args.initial_db, self.namespace))):
            raise OpsFault("ops_state_frozen_identity_mismatch")
        if type(self.chain.get("complete")) is not bool:
            raise OpsFault("ops_state_complete_not_boolean")
        if self.chain.get("unverified_launched_child"):
            raise OpsFault("launch_identity_requires_operator")
        self.argv = validate_launch_template(self.chain.get("launch_template", []))
        recording = []
        for ordinal, segment in enumerate(self.chain["segments"]):
            if segment.get("ordinal") != ordinal or segment.get("owned") is not True or segment.get("registration_sha256") != self.registration_id:
                raise OpsFault("ops_state_segment_identity_mismatch")
            safe_path(segment["db_path"], self.namespace)
            safe_path(segment["gzip_target"], self.namespace)
            if segment["state"] == "recording":
                recording.append(segment)
            elif segment["state"] == "archive_verified":
                archive = safe_path(segment["gzip_path"], self.namespace)
                if sha_file(archive) != (segment["gzip_sha256"], segment["gzip_bytes"]):
                    raise OpsFault("retained_archive_changed")
                if not segment.get("raw_removed"):
                    self.remove_verified_raw(segment)
        if len(recording) > 1:
            raise OpsFault("multiple_active_segments")
        self.active = recording[0] if recording else None
        if self.active is not None and alive(self.active["pid"], self.active["start_ticks"]):
            identity = process_identity(self.active["pid"], self.active["db_path"], self.registration_path, self.source, expected_start=self.active["start_ticks"])
            self.argv = identity["argv"]
        self.failure = self.chain.get("failure")
        if self.chain["complete"] and json.loads(self.chain_path.read_text()) != source_chain(self.chain):
            raise OpsFault("completed_public_chain_mismatch")
        self.event("owned_ops_state_restored")

    def save(self):
        with self.lock:
            self.chain["updated_at_ms"] = utc_ms()
            atomic_json(self.state_path, self.chain)
            atomic_json(self.chain_path, source_chain(self.chain))

    def event(self, code, **detail):
        with self.lock:
            self.chain["events"].append({"at_ms": utc_ms(), "code": code, **detail})
            self.save()

    def remember_failure(self, error, *, stage="supervisor", archive=False, segment=None):
        code = failure_code(error, archive=archive, raw_removed=bool(segment and segment.get("raw_removed")))
        with self.lock:
            self.failure = self.failure or code
            self.chain["failure"] = self.failure
            self.chain["complete"] = False
            self.chain["completed_at_ms"] = None
            detail = {"at_ms": utc_ms(), "stage": stage, "code": code}
            if segment is not None:
                segment["archive_error"] = code
                detail["segment_id"] = segment["segment_id"]
            self.chain.setdefault("failure_diagnostics", []).append(detail)
        try:
            print(canonical({"event_title": "Core OTC collection capacity", **detail}), flush=True)
        except Exception:
            pass  # Even a broken stdout must not interrupt owned cleanup.
        return code

    def best_effort_event(self, code, **detail):
        try:
            self.event(code, **detail)
        except Exception as error:
            self.remember_failure(error, stage="event_persistence")

    def best_effort_status(self, code):
        try:
            return self.status(code)
        except Exception as error:
            self.remember_failure(error, stage="progress_reporting")
            return None

    def fail_closed(self, error):
        """Persistence must never run before or interrupt verified owned closure."""
        code = self.remember_failure(error)
        self.best_effort_event("supervisor_halted", reason=code)
        if self.active is None:
            return
        try:
            # A prior close may have proved closure before reporting failed.
            if self.active.get("state") != "producer_closed":
                self.close_owned("supervisor_failure", failure_cleanup=True)
            self.active = None
        except Exception as stop_error:
            reason = self.remember_failure(stop_error, stage="owned_cleanup")
            self.best_effort_event("owned_stop_requires_operator", reason=reason)

    def adopt(self, pid, database):
        database = safe_path(database, self.namespace)
        identity = process_identity(pid, database, self.registration_path, self.source)
        summary = database_summary(database, self.registration_id)
        if summary["unclosed_session_count"] < 1:
            raise OpsFault("adopted_collector_has_no_open_session")
        self.argv = identity["argv"]
        self.chain["launch_template"] = self.argv
        self.active = {"ordinal": 0, "segment_id": "segment-000000", "db_path": str(database),
                       "gzip_target": str(self.namespace / "segments" / "day-001.sqlite.gz"),
                       "registration_sha256": self.registration_id, "owned": True, "state": "recording",
                       "pid": pid, "start_ticks": identity["start_ticks"], "adopted_at_ms": utc_ms(),
                       "producer_started_at_ms": summary["first_receipt_ms"] or self.registration["start_ms"]}
        self.chain["segments"].append(self.active)
        self.save()

    def assert_frozen(self):
        if sha_file(self.registration_path)[0] != self.source_registration_bytes_sha256:
            raise OpsFault("registration_file_changed")
        verify_source(self.source, self.registration)

    def close_owned(self, reason, *, failure_cleanup=False):
        """File admission may block continuation, never containment of an owned PID."""
        segment = self.active
        if failure_cleanup:
            if not self.failure:
                raise OpsFault("owned_cleanup_requires_diagnosed_failure")
        else:
            self.assert_frozen()
        if alive(segment["pid"], segment["start_ticks"]):
            # A pidfd pins the actual process before identity checks, so PID reuse
            # between verification and delivery cannot signal another process.
            descriptor = None
            try:
                descriptor = os.pidfd_open(segment['pid'], 0)
                try:
                    process_identity(segment["pid"], segment["db_path"], self.registration_path, self.source, expected_start=segment["start_ticks"])
                except OpsFault as error:
                    if str(error) != 'owned_process_not_found' or alive(segment['pid'], segment['start_ticks']):
                        raise
                else:
                    signal.pidfd_send_signal(descriptor, signal.SIGTERM, None, 0)
            except ProcessLookupError:
                # Normal fixed-end exits can race pidfd creation or signal send.
                # Closure is still proved from the owned database below.
                pass
            except OSError:
                raise OpsFault('owned_process_signal_failed') from None
            finally:
                if descriptor is not None:
                    os.close(descriptor)
        deadline = time.monotonic() + 45
        last_progress = 0
        while alive(segment["pid"], segment["start_ticks"]):
            if time.monotonic() >= deadline:
                raise OpsFault("owned_collector_graceful_stop_timeout")
            if time.monotonic() - last_progress >= 10:
                self.best_effort_status("waiting_owned_collector_close")
                last_progress = time.monotonic()
            time.sleep(0.2)
        if segment["pid"] in self.children:
            self.children.pop(segment["pid"]).wait(timeout=1)
        summary = database_summary(segment["db_path"], self.registration_id, checkpoint=True)
        if summary["unclosed_session_count"]:
            raise OpsFault("graceful_stop_session_closure_missing")
        segment.update(summary)
        segment.update({"state": "producer_closed", "closed_at_ms": utc_ms(), "close_reason": reason})
        self.best_effort_event("owned_producer_closed", segment_id=segment["segment_id"])
        return segment

    def launch_next(self):
        self.raise_if_failed()
        self.assert_frozen()
        ordinal = len(self.chain["segments"])
        directory = self.namespace / "segments"
        directory.mkdir(exist_ok=True)
        database = directory / (f"day-{ordinal + 1:03d}.sqlite")
        if database.exists():
            raise OpsFault("new_segment_path_already_exists")
        argv = list(self.argv)
        for name, value in (("--db", str(database)), ("--progress-log", str(directory / f"segment-{ordinal:06d}-progress.jsonl"))):
            for index, arg in enumerate(argv):
                if arg == name:
                    argv[index + 1] = value
                    break
                if arg.startswith(name + "="):
                    argv[index] = name + "=" + value
                    break
            else:
                if name == "--progress-log":
                    argv.extend([name, value])
                else:
                    raise OpsFault("launch_template_database_missing")
        try:
            process = subprocess.Popen(argv, cwd=str(self.source), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                                       env={"PYTHONPATH": str(self.source), "PATH": os.defpath, "LANG": "C.UTF-8"})
        except OSError:
            raise OpsFault("owned_collector_launch_failed") from None
        self.children[process.pid] = process
        try:
            identity = process_identity(process.pid, database, self.registration_path, self.source)
        except Exception:
            # A failed admission is never permission to signal by PID alone.
            # Keep the unverified child explicit for operator investigation.
            self.chain["unverified_launched_child"] = {"pid": process.pid, "db_path": str(database),
                                                        "reason": "launch_identity_requires_operator"}
            raise
        self.active = {"ordinal": ordinal, "segment_id": f"segment-{ordinal:06d}", "db_path": str(database),
                       "gzip_target": str(directory / f"day-{ordinal + 1:03d}.sqlite.gz"),
                       "registration_sha256": self.registration_id, "owned": True, "state": "recording",
                       "pid": process.pid, "start_ticks": identity["start_ticks"], "producer_started_at_ms": utc_ms(),
                       "database_startup_pending": True}
        self.startup_deadlines[process.pid] = time.monotonic() + STARTUP_GRACE_SECONDS
        self.chain["segments"].append(self.active)
        self.event("next_owned_producer_started", segment_id=self.active["segment_id"])

    def enqueue_archive(self, segment):
        def work():
            try:
                self.raise_if_failed()
                self.assert_frozen()
                result = archive_closed(dict(segment), self.namespace, self.registration_id, remove_raw=False)
                with self.lock:
                    segment.update(result)
                    segment["state"] = "archive_verified"
                    self.event("closed_segment_lossless_archived", segment_id=segment["segment_id"], raw_bytes=result["raw_bytes"], gzip_bytes=result["gzip_bytes"])
                # Persist public hashes before removing the owned scratch raw copy.
                self.remove_verified_raw(segment)
                with self.lock:
                    segment["raw_removed"] = True
                    self.event("verified_owned_raw_scratch_removed", segment_id=segment["segment_id"])
            except Exception as error:
                code = self.remember_failure(error, stage="archive_worker", archive=True, segment=segment)
                self.best_effort_event("archive_failed", segment_id=segment["segment_id"], reason=code,
                                       raw_retained=not segment.get("raw_removed", False))
                # The owner consumes every future as well as the in-memory
                # failure; a worker diagnostic failure cannot hide this error.
                raise OpsFault(code) from None
        with self.lock:
            self.raise_if_failed()
            self.assert_frozen()
            self.archives.append(self.executor.submit(work))

    def raise_if_failed(self):
        """A diagnosed failure never admits a new producer or raw removal."""
        code = self.failure or self.chain.get("failure")
        if code:
            raise OpsFault(code)

    def consume_archives(self):
        observed = getattr(self, "observed_archives", set())
        self.observed_archives = observed
        for future in self.archives:
            if future not in observed and future.done():
                try:
                    future.result()
                except Exception as error:
                    self.remember_failure(error, stage="archive_future", archive=True)
                finally:
                    observed.add(future)

    def handoff(self):
        self.raise_if_failed()
        closed = self.close_owned("daily_handoff")
        self.raise_if_failed()
        self.launch_next()
        self.raise_if_failed()
        self.enqueue_archive(closed)

    def remove_verified_raw(self, segment):
        self.raise_if_failed()
        self.assert_frozen()
        if segment.get("owned") is not True or segment.get("state") != "archive_verified" or segment.get("registration_sha256") != self.registration_id:
            raise OpsFault("raw_removal_ownership_missing")
        if alive(segment["pid"], segment["start_ticks"]):
            raise OpsFault("raw_removal_producer_still_alive")
        raw = safe_path(segment["db_path"], self.namespace)
        with closed_raw_lease(raw):
            self._remove_verified_raw(segment, raw)

    def _remove_verified_raw(self, segment, raw):
        archive = safe_path(segment["gzip_path"], self.namespace)
        verify_gzip(archive, segment["raw_sha256"], segment["raw_bytes"])
        if sha_file(archive) != (segment["gzip_sha256"], segment["gzip_bytes"]):
            raise OpsFault("retained_archive_changed")
        if raw.exists():
            summary = database_summary(raw, self.registration_id)
            if summary["unclosed_session_count"] and segment.get("close_reason") != "verified_transport_crash":
                raise OpsFault("raw_removal_sessions_not_closed")
            if sha_file(raw) != (segment["raw_sha256"], segment["raw_bytes"]):
                raise OpsFault("raw_changed_before_removal")
            with self.lock:
                self.raise_if_failed()
                self.assert_frozen()
                raw.unlink()
        segment["raw_removed"] = True

    def status(self, code="collecting"):
        self.assert_frozen()
        now = utc_ms()
        start, end = self.registration["start_ms"], self.registration["end_ms"]
        elapsed = max(0, min(now, end) - start)
        segment = self.active
        summary = {}
        raw_bytes = 0
        if segment:
            startup = (segment.get("database_startup_pending") is True and segment["pid"] in self.children
                       and time.monotonic() < getattr(self, "startup_deadlines", {}).get(segment["pid"], 0))
            if startup:
                process_identity(segment["pid"], segment["db_path"], self.registration_path, self.source,
                                 expected_start=segment["start_ticks"])
            if startup and not Path(segment["db_path"]).exists():
                summary = {"read_status": "awaiting_owned_database_startup"}
            else:
                summary = database_summary(segment["db_path"], self.registration_id, allow_startup=startup)
            raw_bytes = sum(path.stat().st_size for path in (Path(segment["db_path"]), Path(segment["db_path"] + "-wal"), Path(segment["db_path"] + "-shm")) if path.exists())
            segment["database_startup_pending"] = summary.get("read_status") == "awaiting_owned_database_startup"
            if not segment["database_startup_pending"]:
                segment["database_verified_at_ms"] = now
        duration = max(0, now - (segment["producer_started_at_ms"] if segment else now))
        rate = raw_bytes * 1000 / duration if duration else 0
        future = max(0, end - now)
        next_boundary = next((value for value in self.chain["handoff_boundaries_ms"] if value > now), end)
        with self.lock:
            archived_raw = sum(item.get("raw_bytes", 0) for item in self.chain["segments"] if item.get("lossless_verified"))
            archived_gzip = sum(item.get("gzip_bytes", 0) for item in self.chain["segments"] if item.get("lossless_verified"))
            ratio = archived_gzip / archived_raw if archived_raw else None
        free = shutil.disk_usage(self.namespace).free
        report = {"event_title": "Core OTC collection capacity", "at_ms": now, "at_utc": iso(now),
                  "code": code, "registration_sha256": self.registration_id,
                  "percent_done": elapsed * 100 / (end - start), "eta_seconds": future / 1000,
                  "active_segment": segment["segment_id"] if segment else None, "active_raw_bytes": raw_bytes,
                  "raw_bytes_per_second": rate, "projected_remaining_raw_bytes": rate * future / 1000,
                  "next_handoff_ms": next_boundary, "projected_new_bytes_until_handoff": rate * max(0, next_boundary - now) / 1000,
                  "measured_gzip_fraction": ratio, "projected_remaining_gzip_bytes": None if ratio is None else rate * future * ratio / 1000,
                  "free_disk_bytes": free, "reserve_bytes": self.args.reserve_bytes,
                  "capacity_reserve_violated": free < self.args.reserve_bytes, "archive_failure": self.failure,
                  "database_ready": None if segment is None else not segment["database_startup_pending"],
                  "persisted_state": summary}
        line = canonical(report)
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        with self.progress_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
        print(line, flush=True)
        return report

    def request_stop(self, *_):
        self.stop.set()

    def run(self):
        try:
            print(f"tail -f {self.progress_path}", flush=True)
            if self.chain["complete"] is not True:
                self.collect()
        except Exception as error:
            self.fail_closed(error)
        finally:
            self.finish()
        return 0 if self.chain["complete"] else 2

    def collect(self):
        pending = [segment for segment in self.chain["segments"] if segment["state"] == "producer_closed"]
        if self.failure:
            raise OpsFault(self.failure)
        if self.active is None and utc_ms() < self.registration["end_ms"]:
            self.launch_next()
        for segment in pending:
            self.enqueue_archive(segment)
        boundaries = iter(self.chain["handoff_boundaries_ms"])
        boundary = next(boundaries)
        while boundary <= utc_ms() and boundary < self.registration["end_ms"]:
            boundary = next(boundaries)
        restart_count = integer(self.chain.get("transport_restart_count", 0), "invalid_restart_count")
        last_status = 0
        while not self.stop.is_set():
            self.consume_archives()
            if self.failure:
                raise OpsFault(self.failure)
            now = utc_ms()
            startup_due = (self.active is not None and self.active.get("database_startup_pending") is True
                           and time.monotonic() >= getattr(self, "startup_deadlines", {}).get(self.active["pid"], 0))
            if time.monotonic() - last_status >= 30 or startup_due:
                report = self.status()
                last_status = time.monotonic()
                if report["capacity_reserve_violated"]:
                    raise OpsFault("disk_reserve_violated")
            if now >= self.registration["end_ms"]:
                if self.active is not None:
                    closed = self.close_owned("registered_end")
                    self.raise_if_failed()
                    self.enqueue_archive(closed)
                    self.active = None
                break
            if not alive(self.active["pid"], self.active["start_ticks"]):
                summary = database_summary(self.active["db_path"], self.registration_id, checkpoint=True)
                if not restart_allowed(summary) or restart_count >= 3:
                    raise OpsFault("producer_exit_not_eligible_for_transport_restart")
                self.active.update(summary)
                self.active.update({"state": "producer_closed", "closed_at_ms": now, "close_reason": "verified_transport_crash"})
                closed = self.active
                self.raise_if_failed()
                restart_count += 1
                self.chain["transport_restart_count"] = restart_count
                self.launch_next()
                self.raise_if_failed()
                self.enqueue_archive(closed)
            elif now >= boundary:
                self.handoff()  # New receipt producer starts before old compression.
                boundary = next(boundaries)
            self.stop.wait(0.25)
        if self.stop.is_set() and self.active is not None:
            closed = self.close_owned("supervisor_requested_stop")
            self.raise_if_failed()
            self.enqueue_archive(closed)
            self.active = None

    def finish(self):
        """Drain futures and retain failure evidence even when disk reporting is broken."""
        last_status = 0
        while any(not future.done() for future in self.archives):
            self.consume_archives()
            if time.monotonic() - last_status >= 10:
                self.best_effort_status("waiting_closed_archives")
                last_status = time.monotonic()
            if self.failure and self.active is not None:
                self.fail_closed(OpsFault(self.failure))
            time.sleep(0.2)
        self.consume_archives()
        if self.failure and self.active is not None:
            self.fail_closed(OpsFault(self.failure))
        try:
            self.executor.shutdown(wait=True)
        except Exception as error:
            self.fail_closed(error)
        with self.lock:
            self.chain["complete"] = (self.failure is None and self.active is None and utc_ms() >= self.registration["end_ms"]
                                      and not self.chain.get("unverified_launched_child")
                                      and all(segment.get("state") == "archive_verified" for segment in self.chain["segments"]))
            self.chain["physically_closed"] = self.active is None and not self.chain.get("unverified_launched_child")
            self.chain["failure"] = self.failure
            self.chain["completed_at_ms"] = utc_ms() if self.chain["complete"] else None
        self.best_effort_status("complete" if self.chain["complete"] else "closed_incomplete")
        try:
            self.save()
        except Exception as error:
            self.fail_closed(error)
            # Retry an incomplete record once; persistent ENOSPC cannot prevent
            # physical closure or change the exit status into success.
            try:
                self.save()
            except Exception as retry_error:
                self.remember_failure(retry_error, stage="final_state_persistence")
        try:
            self.process_lock.close()
        except Exception as error:
            self.remember_failure(error, stage="supervisor_lock_close")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    supervise = sub.add_parser("supervise")
    supervise.add_argument("--source", required=True)
    supervise.add_argument("--registration", required=True)
    supervise.add_argument("--namespace", required=True)
    supervise.add_argument("--adopt-pid", type=int, required=True)
    supervise.add_argument("--initial-db", required=True)
    supervise.add_argument("--progress-log", required=True)
    supervise.add_argument("--reserve-bytes", type=int, default=536_870_912)
    args = parser.parse_args(argv)
    if args.reserve_bytes <= 0:
        parser.error("reserve must be positive")
    try:
        runner = Supervisor(args)
        signal.signal(signal.SIGINT, runner.request_stop)
        signal.signal(signal.SIGTERM, runner.request_stop)
        return runner.run()
    except Exception as exc:
        code = str(exc) if isinstance(exc, OpsFault) else "supervisor_initialization_failed"
        try:
            print(canonical({"event_title": "Core OTC collection capacity", "at_ms": utc_ms(), "code": code}), flush=True)
        except OSError:
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
