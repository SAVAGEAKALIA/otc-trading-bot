"""Atomic append-only SQLite storage, session journal, and consistent backup boundary."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
import uuid
import fcntl
from .protocol import SCHEMA, canonical, digest, utc_ms, validate_registration


class StorageFault(RuntimeError):
    pass


class IdentityConflict(StorageFault):
    pass


DDL = """
CREATE TABLE IF NOT EXISTS registration(singleton INTEGER PRIMARY KEY CHECK(singleton=1), record_json TEXT NOT NULL, record_sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(session_id TEXT NOT NULL, transition TEXT NOT NULL CHECK(transition IN ('open','close')), at_ms INTEGER NOT NULL, detail_json TEXT NOT NULL, PRIMARY KEY(session_id,transition));
CREATE TABLE IF NOT EXISTS receipts(frame_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, sequence INTEGER NOT NULL, received_at_ms INTEGER NOT NULL, monotonic_ns INTEGER NOT NULL, envelope_json TEXT NOT NULL, envelope_sha256 TEXT NOT NULL, UNIQUE(session_id,sequence));
CREATE TABLE IF NOT EXISTS observations(event_id TEXT PRIMARY KEY, frame_id TEXT NOT NULL REFERENCES receipts(frame_id), asset TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL, available_ms INTEGER NOT NULL, observation_json TEXT NOT NULL, lineage_json TEXT NOT NULL, clock_status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS health(health_id TEXT PRIMARY KEY, session_id TEXT, at_ms INTEGER NOT NULL, code TEXT NOT NULL, detail_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS observations_causal ON observations(asset,kind,available_ms);
CREATE INDEX IF NOT EXISTS health_at ON health(at_ms);
"""


class Store:
    def __init__(self, path, registration):
        self.path = Path(path).resolve()
        if not self.path.is_relative_to(Path("/tmp")):
            raise ValueError("fresh collector database must be under /tmp")
        validate_registration(registration)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.failed = False
        self.registration = registration
        if self.path.exists():
            probe = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
            try:
                names = {row[0] for row in probe.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if names != {"registration", "sessions", "receipts", "observations", "health"}:
                    raise IdentityConflict("not_a_fresh_collector_database")
                registered = probe.execute("SELECT record_json,record_sha256 FROM registration WHERE singleton=1").fetchone()
                if registered != (canonical(registration), digest(registration)):
                    raise IdentityConflict("registration_resume_mismatch")
            finally:
                probe.close()
        self.process_lock = self.path.with_name(self.path.name + ".lock").open("a")
        try:
            fcntl.flock(self.process_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.process_lock.close()
            raise StorageFault("another_collector_owns_database") from exc
        try:
            self.connection = sqlite3.connect(str(self.path), timeout=1.0, check_same_thread=False)
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute("PRAGMA busy_timeout=1000")
            trigger_sql = []
            for table in ("registration", "sessions", "receipts", "observations", "health"):
                for action in ("UPDATE", "DELETE"):
                    trigger_sql.append(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'append_only'); END;")
            # One atomic schema transaction avoids one fsync per table/trigger.
            self.connection.executescript("BEGIN IMMEDIATE;\n" + DDL + "\n".join(trigger_sql) + "\nCOMMIT;")
            row = self.connection.execute("SELECT record_json,record_sha256 FROM registration WHERE singleton=1").fetchone()
            expected = canonical(registration)
            if row is None:
                if self.connection.execute("SELECT count(*) FROM receipts").fetchone()[0]:
                    raise IdentityConflict("unregistered_existing_database")
                self.connection.execute("INSERT INTO registration VALUES(1,?,?)", (expected, digest(registration)))
                self.connection.commit()
            elif row != (expected, digest(registration)):
                raise IdentityConflict("registration_resume_mismatch")
            result = self.connection.execute("PRAGMA quick_check").fetchone()[0]
            if result != "ok":
                raise StorageFault("database_integrity_failure")
        except (sqlite3.Error, OSError, StorageFault) as exc:
            self._fallback("storage_open_failure")
            if hasattr(self, "connection"):
                self.connection.close()
            self.process_lock.close()
            raise StorageFault("storage_open_failure") from exc

    def _fallback(self, code):
        """Best effort safe emergency evidence when the database itself is unavailable."""
        self.failed = True
        marker = self.path.with_name(self.path.name + ".failure.jsonl")
        try:
            with marker.open("a", encoding="utf-8") as handle:
                handle.write(canonical({"at_ms": utc_ms(), "code": code, "database": self.path.name}) + "\n")
                handle.flush()
                import os
                os.fsync(handle.fileno())
        except OSError:
            pass

    def _transaction(self, call):
        with self.lock:
            if self.failed:
                raise StorageFault("storage_halted")
            try:
                with self.connection:
                    return call()
            except IdentityConflict:
                self._fallback("identity_conflict")
                raise
            except (sqlite3.Error, OSError) as exc:
                self._fallback("storage_write_failure")
                raise StorageFault("storage_write_failure") from exc

    def open_session(self, *, at_ms=None, session_id=None):
        session_id = session_id or str(uuid.uuid4())
        at_ms = utc_ms() if at_ms is None else at_ms
        def insert():
            previous = self.connection.execute("SELECT s.session_id FROM sessions s WHERE s.transition='open' AND NOT EXISTS(SELECT 1 FROM sessions c WHERE c.session_id=s.session_id AND c.transition='close')").fetchall()
            if previous:
                self._insert_health("partial_crash_recovery", at_ms, session_id, {"unclosed_session_count": len(previous)})
            self.connection.execute("INSERT INTO sessions VALUES(?,?,?,?)", (session_id, "open", at_ms, canonical({"registration_sha256": self.registration["registration_sha256"]})))
            return session_id
        return self._transaction(insert)

    def close_session(self, session_id, *, at_ms=None, code="graceful_close"):
        at_ms = utc_ms() if at_ms is None else at_ms
        return self._transaction(lambda: self.connection.execute("INSERT INTO sessions VALUES(?,?,?,?)", (session_id, "close", at_ms, canonical({"code": code}))))

    def _insert_health(self, code, at_ms, session_id, detail):
        self.connection.execute("INSERT INTO health VALUES(?,?,?,?,?)", (str(uuid.uuid4()), session_id, at_ms, code, canonical(detail)))

    def health(self, code, at_ms, session_id=None, **detail):
        # Details must be controlled primitives supplied by collector code, never broker error text.
        return self._transaction(lambda: self._insert_health(code, at_ms, session_id, detail))

    def append(self, envelope):
        encoded, fingerprint = canonical(envelope), digest(envelope)
        def insert():
            row = self.connection.execute("SELECT envelope_json,envelope_sha256 FROM receipts WHERE frame_id=?", (envelope["frame_id"],)).fetchone()
            if row is not None:
                if row != (encoded, fingerprint):
                    raise IdentityConflict("same_receipt_id_conflicting_values")
                return False
            self.connection.execute("INSERT INTO receipts VALUES(?,?,?,?,?,?,?)", (envelope["frame_id"], envelope["session_id"], envelope["sequence"], envelope["received_at_ms"], envelope["monotonic_ns"], encoded, fingerprint))
            for event in envelope["events"]:
                obs, lineage = event["observation"], event["lineage"]
                self.connection.execute("INSERT INTO observations(event_id,frame_id,asset,kind,source,available_ms,observation_json,lineage_json,clock_status) VALUES(?,?,?,?,?,?,?,?,?)", (obs["event_id"], envelope["frame_id"], obs["asset"], obs["kind"], obs["source"], obs["available_ms"], canonical(obs), canonical(lineage), lineage["clock_status"]))
                if lineage["clock_status"] != "ok":
                    self._insert_health(lineage["clock_status"], envelope["received_at_ms"], envelope["session_id"], {"event_id": obs["event_id"], "asset": obs["asset"]})
            if envelope["health"] is not None:
                info = envelope["health"]
                self._insert_health(info["code"], envelope["received_at_ms"], envelope["session_id"], {k: v for k, v in info.items() if k != "code"})
            return True
        return self._transaction(insert)

    def backup(self, destination):
        destination = Path(destination).resolve()
        if not destination.is_relative_to(Path("/tmp")) or destination.exists():
            raise ValueError("backup requires a new /tmp path")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            target = sqlite3.connect(str(destination))
            try:
                self.connection.backup(target)
            finally:
                target.close()
        return destination

    def close(self):
        with self.lock:
            self.connection.close()
            self.process_lock.close()
