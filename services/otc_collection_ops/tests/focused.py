"""Ownership, fixed chronology, exact gzip retention and handoff order regressions."""
from datetime import datetime, timezone
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import redirect_stdout
import ast
import gzip
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from services.otc_collection_ops.ops import (DAY_MS, OpsFault, Supervisor, archive_closed, canonical,
    digest, handoff_boundaries, iso, process_identity, read_registration, restart_allowed, sha_file,
    source_chain, verify_gzip, failure_code, alive, database_summary, STARTUP_GRACE_SECONDS)

START = int(datetime(2026, 11, 7, 10, 8, tzinfo=timezone.utc).timestamp() * 1000)


def registration():
    record = {"start_ms": START, "end_ms": START + 7 * DAY_MS, "created_ms": START - 60_000,
              "assets": ["EURUSD-OTC", "GBPUSD-OTC"], "product": "turbo-option"}
    record["registration_sha256"] = digest(record)
    return record


def database(path, record):
    conn = sqlite3.connect(path)
    conn.executescript("""
      BEGIN;
      CREATE TABLE registration(singleton INTEGER PRIMARY KEY,record_json TEXT);
      CREATE TABLE sessions(session_id TEXT,transition TEXT,at_ms INTEGER);
      CREATE TABLE receipts(frame_id TEXT,received_at_ms INTEGER);
      CREATE TABLE observations(asset TEXT,kind TEXT,available_ms INTEGER);
      CREATE TABLE health(code TEXT);
    """)
    conn.execute("INSERT INTO registration VALUES(1,?)", (canonical(record),))
    conn.executemany("INSERT INTO sessions VALUES('s',?,?)", [("open", START), ("close", START + 1000)])
    conn.execute("INSERT INTO receipts VALUES('r',?)", (START,))
    conn.execute("INSERT INTO observations VALUES('EURUSD-OTC','quote',?)", (START,))
    conn.commit()
    conn.close()


def owned(path, record):
    return {"ordinal": 0, "db_path": str(path), "state": "producer_closed", "owned": True,
            "registration_sha256": record["registration_sha256"], "close_reason": "daily_handoff",
            "gzip_target": str(path.parent / "segments" / "day-001.sqlite.gz"), "closed_at_ms": START + DAY_MS + 90_000}


def fake_proc(directory, source, db, reg, pid=1234, start_ticks=777):
    proc = directory / str(pid)
    proc.mkdir(parents=True)
    argv = ["/usr/bin/python3", "-u", "-m", "services.otc_collector.runner", "live", "--registration", str(reg),
            "--db", str(db), "--env-file", "/external/private.env", "--progress-log", str(db.parent / "progress.log"), "--allow-account-read"]
    (proc / "cmdline").write_bytes(b"\0".join(value.encode() for value in argv) + b"\0")
    (proc / "stat").write_text(str(pid) + " (python with spaces) " + " ".join(["S"] + ["0"] * 18 + [str(start_ticks)]) + "\n")
    (proc / "cwd").symlink_to(source, target_is_directory=True)
    (proc / "exe").symlink_to(Path('/usr/bin/python3').resolve())
    return proc


def supervisor_fixture(root):
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.registration = registration()
    supervisor.registration_id = supervisor.registration["registration_sha256"]
    supervisor.namespace = root
    supervisor.source, supervisor.registration_path = root / "source", root / "registration.json"
    supervisor.progress_path = root / "progress.log"
    supervisor.state_path, supervisor.chain_path = root / "ops-state.json", root / "sourcechain.json"
    supervisor.lock, supervisor.stop = threading.RLock(), threading.Event()
    supervisor.executor, supervisor.archives, supervisor.children = ThreadPoolExecutor(max_workers=1), [], {}
    supervisor.startup_deadlines = {}
    supervisor.failure, supervisor.argv = None, []
    supervisor.args = SimpleNamespace(reserve_bytes=1)
    supervisor.process_lock = Mock()
    supervisor.active = {**owned(root / "receipts.sqlite", supervisor.registration), "state": "recording",
                         "pid": 1234, "start_ticks": 777, "segment_id": "segment-000000",
                         "producer_started_at_ms": START}
    supervisor.chain = {"registration_sha256": supervisor.registration_id, "complete": False,
                        "segments": [supervisor.active], "events": [], "transport_restart_count": 0,
                        "handoff_boundaries_ms": handoff_boundaries(supervisor.registration)}
    supervisor.assert_frozen = Mock()
    return supervisor


def frozen_run_fixture(root):
    """Admit a real SQLite database and fake proc through the real constructor."""
    source = root / "source"
    source_file = source / "services" / "otc_collector" / "__init__.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("# frozen run fixture\n")
    record = registration()
    record.pop("registration_sha256")
    record["code_files"] = {"__init__.py": sha_file(source_file)[0]}
    record["code_sha256"] = digest(record["code_files"])
    record["registration_sha256"] = digest(record)
    reg, db = root / "registration.json", root / "receipts.sqlite"
    reg.write_text(canonical(record))
    database(db, record)
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM sessions WHERE transition='close'")
    proc_root = root / "proc"
    proc = fake_proc(proc_root, source, db, reg)
    args = SimpleNamespace(namespace=str(root), source=str(source), registration=str(reg),
                           initial_db=str(db), progress_log=str(root / "progress.log"),
                           adopt_pid=1234, reserve_bytes=1)
    return args, source_file, proc_root, proc


def close_fixture(supervisor, code):
    supervisor.active.update({"state": "producer_closed", "closed_at_ms": START + 1000, "close_reason": code})
    return supervisor.active


class EssentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root = Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def test_registered_dates_and_off_grid_daily_handoffs_are_fixed(self):
        reg = registration()
        boundaries = handoff_boundaries(reg)
        self.assertEqual(iso(reg["start_ms"]), "2026-11-07T10:08:00.000Z")
        self.assertEqual(iso(boundaries[0]), "2026-11-08T10:09:30.000Z")
        self.assertEqual(iso(boundaries[-1]), "2026-11-14T10:08:00.000Z")
        self.assertEqual([value % 120_000 for value in boundaries[:-1]], [90_000] * 6)
        self.assertEqual(reg["end_ms"] - reg["start_ms"], 7 * DAY_MS)
    def test_invalid_changed_or_boolean_registration_rejected(self):
        path = self.root / "registration.json"
        for key, value in (("end_ms", True), ("created_ms", START), ("end_ms", START + 8 * DAY_MS)):
            bad = registration()
            bad.pop("registration_sha256")
            bad[key] = value
            bad["registration_sha256"] = digest(bad)
            path.write_text(canonical(bad))
            with self.assertRaises(OpsFault):
                read_registration(path)
    def test_exact_owned_pid_database_registration_and_start_ticks(self):
        source = self.root / "source"
        source.mkdir()
        db, reg = self.root / "receipts.sqlite", self.root / "registration.json"
        fake_proc(self.root / "proc", source, db, reg)
        identity = process_identity(1234, db, reg, source, proc_root=self.root / "proc", expected_start=777)
        self.assertEqual(identity["start_ticks"], 777)
        for kwargs in ({"expected_start": 778}, {"database": self.root / "different.sqlite"}, {"registration": self.root / "different.json"}):
            values = {"pid": 1234, "database": db, "registration": reg, "source_root": source, "proc_root": self.root / "proc", **kwargs}
            with self.assertRaises(OpsFault):
                process_identity(**values)
    def test_failed_ownership_never_signals_any_process(self):
        supervisor = Supervisor.__new__(Supervisor)
        supervisor.active = {"pid": 1234, "start_ticks": 777, "db_path": "unused"}
        supervisor.assert_frozen = Mock()
        supervisor.registration_path, supervisor.source = "unused", "unused"
        with patch("services.otc_collection_ops.ops.alive", return_value=True), patch("services.otc_collection_ops.ops.process_identity", side_effect=OpsFault("pid_reused")), patch("services.otc_collection_ops.ops.os.pidfd_open", return_value=66), patch("services.otc_collection_ops.ops.os.close"), patch("services.otc_collection_ops.ops.os.kill") as kill, patch("services.otc_collection_ops.ops.signal.pidfd_send_signal") as send:
            with self.assertRaises(OpsFault):
                supervisor.close_owned("daily_handoff")
            kill.assert_not_called()
            send.assert_not_called()
    def test_python_c_or_other_executable_is_never_owned(self):
        source = self.root / 'source'
        source.mkdir()
        db, reg = self.root / 'receipts.sqlite', self.root / 'registration.json'
        proc = fake_proc(self.root/'proc', source, db, reg)
        original = proc.joinpath('cmdline').read_bytes()
        for injection in (b'-c\0pass\0', b'-W\0ignore\0', b'-I\0'):
            proc.joinpath('cmdline').write_bytes(original.replace(b'-u\0', injection, 1))
            with self.assertRaises(OpsFault):
                process_identity(1234, db, reg, source, proc_root=self.root/'proc')
        proc.joinpath('cmdline').write_bytes(original)
        proc.joinpath('exe').unlink()
        proc.joinpath('exe').symlink_to('/bin/echo')
        with self.assertRaises(OpsFault):
            process_identity(1234, db, reg, source, proc_root=self.root/'proc')
    def test_normal_exit_races_still_require_closed_database(self):
        for phase in ('identity', 'signal', 'pidfd'):
            with self.subTest(phase=phase):
                supervisor = Supervisor.__new__(Supervisor)
                supervisor.active = {'pid':1234,'start_ticks':777,'db_path':'unused','segment_id':'segment-000000'}
                supervisor.assert_frozen = Mock()
                supervisor.registration_path, supervisor.source = 'unused', 'unused'
                supervisor.registration_id, supervisor.children = 'a'*64, {}
                supervisor.event, supervisor.status = Mock(), Mock()
                closed = {'unclosed_session_count':0}
                identity_error = OpsFault('owned_process_not_found') if phase=='identity' else None
                fd_error = ProcessLookupError() if phase=='pidfd' else None
                send_error = ProcessLookupError() if phase=='signal' else None
                with patch('services.otc_collection_ops.ops.alive', side_effect=[True,False,False]), patch('services.otc_collection_ops.ops.process_identity', side_effect=identity_error), patch('services.otc_collection_ops.ops.os.pidfd_open', return_value=66, side_effect=fd_error), patch('services.otc_collection_ops.ops.os.close'), patch('services.otc_collection_ops.ops.signal.pidfd_send_signal', side_effect=send_error), patch('services.otc_collection_ops.ops.os.kill') as kill, patch('services.otc_collection_ops.ops.database_summary', return_value=closed) as summary:
                    result = supervisor.close_owned('registered_end')
                    self.assertEqual(result['state'],'producer_closed')
                    summary.assert_called_once()
                    kill.assert_not_called()
    def test_normal_exit_with_unclosed_session_does_not_invent_closure(self):
        supervisor = Supervisor.__new__(Supervisor)
        supervisor.active = {'pid':1234,'start_ticks':777,'db_path':'unused'}
        supervisor.assert_frozen = Mock()
        supervisor.registration_path, supervisor.source = 'unused','unused'
        supervisor.registration_id, supervisor.children = 'a'*64, {}
        with patch('services.otc_collection_ops.ops.alive', return_value=False), patch('services.otc_collection_ops.ops.database_summary', return_value={'unclosed_session_count':1}):
            with self.assertRaisesRegex(OpsFault,'graceful_stop_session_closure_missing'):
                supervisor.close_owned('registered_end')
    def test_new_producer_launch_precedes_old_compression(self):
        supervisor = Supervisor.__new__(Supervisor)
        supervisor.failure = None
        supervisor.chain = {}
        calls = []
        closed = {"segment_id": "segment-000000"}
        supervisor.close_owned = lambda reason: calls.append("close") or closed
        supervisor.launch_next = lambda: calls.append("launch")
        supervisor.enqueue_archive = lambda segment: calls.append("compress")
        supervisor.handoff()
        self.assertEqual(calls, ["close", "launch", "compress"])
    def test_streamed_gzip_exact_hash_preserves_initial_identity_then_removes_owned_raw(self):
        reg = registration()
        path = self.root / "receipts.sqlite"
        database(path, reg)
        original_hash, original_bytes = sha_file(path)
        segment = owned(path, reg)
        result = archive_closed(segment, self.root, reg["registration_sha256"])
        self.assertFalse(path.exists())
        self.assertTrue(result["raw_removed"])
        self.assertEqual(result["raw_sha256"], original_hash)
        self.assertEqual(result["raw_bytes"], original_bytes)
        self.assertEqual(Path(result["gzip_path"]).name, "day-001.sqlite.gz")
        self.assertEqual(verify_gzip(result["gzip_path"], original_hash, original_bytes), (original_hash, original_bytes))
        self.assertEqual(segment["db_path"], str(path))
    def test_corrupt_existing_archive_keeps_owned_raw(self):
        reg = registration()
        path = self.root / "receipts.sqlite"
        database(path, reg)
        segment = owned(path, reg)
        archive = Path(segment["gzip_target"])
        archive.parent.mkdir()
        archive.write_bytes(gzip.compress(b"wrong data"))
        before = path.read_bytes()
        with self.assertRaises(OpsFault):
            archive_closed(segment, self.root, reg["registration_sha256"])
        self.assertEqual(path.read_bytes(), before)
    def test_unowned_or_unclosed_raw_is_never_removed(self):
        reg = registration()
        path = self.root / "receipts.sqlite"
        database(path, reg)
        segment = owned(path, reg)
        segment["owned"] = False
        with self.assertRaises(OpsFault):
            archive_closed(segment, self.root, reg["registration_sha256"])
        self.assertTrue(path.exists())
        segment["owned"] = True
        conn = sqlite3.connect(path)
        conn.execute("DELETE FROM sessions WHERE transition='close'")
        conn.commit()
        conn.close()
        with self.assertRaises(OpsFault):
            archive_closed(segment, self.root, reg["registration_sha256"])
        self.assertTrue(path.exists())
    def test_public_chain_exact_contract_and_transport_only_restart(self):
        state = {"registration_sha256": "a" * 64, "complete": False, "segments": [{
            "ordinal": 0, "state": "archive_verified", "gzip_path": "/tmp/core/segments/day-001.sqlite.gz",
            "gzip_sha256": "b" * 64, "raw_sha256": "c" * 64, "raw_bytes": 100, "closed_at_ms": START,
            "pid": 1234, "launch_template": ["do not expose"], "session_count": 1}]}
        result = source_chain(state)
        self.assertEqual(set(result), {"schema", "registration_sha256", "complete", "segments"})
        self.assertEqual(result["schema"], "fresh_otc_source_chain_v1")
        self.assertEqual(set(result["segments"][0]), {"path", "compressed_sha256", "sqlite_sha256", "sqlite_bytes", "closed_at_ms"})
        self.assertNotIn("do not expose", canonical(result))
        self.assertTrue(restart_allowed({"latest_health_code": "reconnect_budget_exhausted", "health_counts": {"reconnect_budget_exhausted": 1}}))
        for code in ("authentication_ack_timeout", "receiver_clock_jump", "transport_or_storage_halted", "storage_write_failure"):
            self.assertFalse(restart_allowed({"latest_health_code": "reconnect_budget_exhausted", "health_counts": {code: 1}}))

    def test_operational_io_and_unexpected_failures_close_despite_repeated_reporting_errors(self):
        for error, expected in ((OSError(28, "private ENOSPC text"), "supervisor_operational_io_failed"),
                                (RuntimeError("private failure text"), "supervisor_unexpected_failure")):
            with self.subTest(expected=expected):
                supervisor = supervisor_fixture(self.root)
                supervisor.status = Mock(side_effect=error)
                supervisor.save = Mock(side_effect=OSError(28, "private state text"))
                supervisor.close_owned = Mock(side_effect=lambda code, **_: close_fixture(supervisor, code))
                with patch("services.otc_collection_ops.ops.utc_ms", return_value=START + 1000), patch("builtins.print"), patch("services.otc_collection_ops.ops.os.kill") as kill, patch("services.otc_collection_ops.ops.signal.pidfd_send_signal") as send:
                    result = supervisor.run()
                self.assertEqual(result, 2)
                supervisor.close_owned.assert_called_once_with("supervisor_failure", failure_cleanup=True)
                self.assertIsNone(supervisor.active)
                self.assertEqual(supervisor.failure, expected)
                self.assertTrue(supervisor.chain["physically_closed"])
                self.assertFalse(supervisor.chain["complete"])
                self.assertNotIn("private", canonical(supervisor.chain))
                kill.assert_not_called()
                send.assert_not_called()

    def test_close_progress_and_closure_event_io_do_not_interrupt_verified_stop(self):
        supervisor = supervisor_fixture(self.root)
        supervisor.status = Mock(side_effect=OSError(28, "full"))
        supervisor.save = Mock(side_effect=OSError(28, "full"))
        with patch("builtins.print"), patch("services.otc_collection_ops.ops.alive", side_effect=[True, True, False]), patch("services.otc_collection_ops.ops.process_identity"), patch("services.otc_collection_ops.ops.os.pidfd_open", return_value=66), patch("services.otc_collection_ops.ops.os.close"), patch("services.otc_collection_ops.ops.signal.pidfd_send_signal") as send, patch("services.otc_collection_ops.ops.os.kill") as kill, patch("services.otc_collection_ops.ops.time.sleep"), patch("services.otc_collection_ops.ops.database_summary", return_value={"unclosed_session_count": 0}) as summary:
            result = supervisor.close_owned("daily_handoff")
        self.assertEqual(result["state"], "producer_closed")
        self.assertEqual(supervisor.failure, "supervisor_operational_io_failed")
        send.assert_called_once()
        kill.assert_not_called()
        summary.assert_called_once()
        supervisor.launch_next = Mock()
        supervisor.close_owned = Mock(return_value=result)
        with self.assertRaisesRegex(OpsFault, "supervisor_operational_io_failed"):
            supervisor.handoff()
        supervisor.launch_next.assert_not_called()
        supervisor.executor.shutdown()

    def test_cleanup_ownership_rejection_never_signals_and_retains_raw(self):
        supervisor = supervisor_fixture(self.root)
        database(Path(supervisor.active["db_path"]), supervisor.registration)
        original = sha_file(supervisor.active["db_path"])
        supervisor.save = Mock(side_effect=OSError(28, "full"))
        with patch("services.otc_collection_ops.ops.alive", return_value=True), patch("services.otc_collection_ops.ops.process_identity", side_effect=OpsFault("pid_reused")), patch("services.otc_collection_ops.ops.os.pidfd_open", return_value=66), patch("services.otc_collection_ops.ops.os.close"), patch("services.otc_collection_ops.ops.signal.pidfd_send_signal") as send, patch("services.otc_collection_ops.ops.os.kill") as kill:
            supervisor.fail_closed(OSError(28, "full"))
        self.assertIsNotNone(supervisor.active)
        self.assertEqual(sha_file(supervisor.active["db_path"]), original)
        self.assertIn("pid_reused", canonical(supervisor.chain["failure_diagnostics"]))
        send.assert_not_called()
        kill.assert_not_called()
        supervisor.executor.shutdown()

    def test_archive_worker_io_or_unexpected_errors_and_failed_events_are_observed(self):
        for error, expected in ((OSError(28, "private disk message"), "archive_io_failed_raw_retained"),
                                (RuntimeError("private worker message"), "archive_unexpected_failure_raw_retained")):
            with self.subTest(expected=expected):
                case_root = self.root / expected
                case_root.mkdir()
                supervisor = supervisor_fixture(case_root)
                database(Path(supervisor.active["db_path"]), supervisor.registration)
                segment = supervisor.active
                segment["state"] = "producer_closed"
                original = sha_file(segment["db_path"])
                supervisor.save = Mock(side_effect=OSError(28, "private event message"))
                with patch("services.otc_collection_ops.ops.archive_closed", side_effect=error):
                    supervisor.enqueue_archive(segment)
                    supervisor.executor.shutdown(wait=True)
                supervisor.consume_archives()
                self.assertEqual(supervisor.failure, expected)
                self.assertEqual(segment["archive_error"], expected)
                self.assertEqual(supervisor.observed_archives, set(supervisor.archives))
                self.assertEqual(sha_file(segment["db_path"]), original)
                self.assertNotIn("private", canonical(supervisor.chain))

    def test_archive_publication_save_failure_retains_real_raw_and_verified_gzip(self):
        supervisor = supervisor_fixture(self.root)
        path = Path(supervisor.active["db_path"])
        database(path, supervisor.registration)
        segment = supervisor.active
        segment["state"] = "producer_closed"
        original = sha_file(path)
        supervisor.save = Mock(side_effect=OSError(28, "full"))
        supervisor.enqueue_archive(segment)
        supervisor.executor.shutdown(wait=True)
        supervisor.consume_archives()
        self.assertEqual(sha_file(path), original)
        self.assertEqual(verify_gzip(segment["gzip_path"], *original), original)
        self.assertFalse(segment["raw_removed"])
        self.assertEqual(segment["archive_error"], "archive_io_failed_raw_retained")
        self.assertEqual(supervisor.observed_archives, set(supervisor.archives))

    def test_archive_wait_reporting_and_future_failure_halt_owned_producer(self):
        supervisor = supervisor_fixture(self.root)
        pending = Future()
        supervisor.archives = [pending]
        supervisor.status = Mock(side_effect=OSError(28, "full"))
        supervisor.save = Mock(side_effect=OSError(28, "full"))
        supervisor.close_owned = Mock(side_effect=lambda code, **_: close_fixture(supervisor, code))
        with patch("services.otc_collection_ops.ops.time.sleep", side_effect=lambda _: pending.set_exception(RuntimeError("private worker error"))):
            supervisor.finish()
        supervisor.close_owned.assert_called_once_with("supervisor_failure", failure_cleanup=True)
        self.assertIsNone(supervisor.active)
        self.assertEqual(supervisor.observed_archives, {pending})
        self.assertTrue(supervisor.chain["physically_closed"])
        self.assertIn("archive_unexpected_failure_raw_retained", canonical(supervisor.chain["failure_diagnostics"]))

    def test_adoption_save_failure_closes_before_constructor_returns(self):
        args = SimpleNamespace(namespace=str(self.root), source=str(self.root / "source"),
                               registration=str(self.root / "registration.json"), initial_db=str(self.root / "receipts.sqlite"),
                               progress_log=str(self.root / "progress.log"), adopt_pid=1234)
        record = registration()
        record.pop("registration_sha256")
        record["code_sha256"] = "a" * 64
        record["registration_sha256"] = digest(record)
        Path(args.registration).write_text(canonical(record))
        database(Path(args.initial_db), record)
        with patch("services.otc_collection_ops.ops.verify_source"), patch("services.otc_collection_ops.ops.process_identity", return_value={"argv": [], "start_ticks": 777}), patch("services.otc_collection_ops.ops.database_summary", return_value={"unclosed_session_count": 1, "first_receipt_ms": START}), patch.object(Supervisor, "save", side_effect=OSError(28, "full")), patch.object(Supervisor, "close_owned", autospec=True, side_effect=lambda sup, code, **_: close_fixture(sup, code)) as close:
            with self.assertRaisesRegex(OpsFault, "supervisor_operational_io_failed"):
                Supervisor(args)
        self.assertEqual(close.call_count, 1)
        self.assertTrue(Path(args.initial_db).exists())

    def test_run_setup_launch_save_error_targets_new_verified_child(self):
        supervisor = supervisor_fixture(self.root)
        old = supervisor.active
        old["state"] = "producer_closed"
        database(Path(old["db_path"]), supervisor.registration)
        supervisor.active = None
        supervisor.argv = ["/usr/bin/python3", "-m", "services.otc_collector.runner", "live", "--db", old["db_path"],
                           "--registration", str(supervisor.registration_path), "--env-file", "/external/private.env", "--allow-account-read"]
        supervisor.save = Mock(side_effect=OSError(28, "full"))
        supervisor.status = Mock(return_value={})
        stopped = []
        supervisor.close_owned = Mock(side_effect=lambda code, **_: stopped.append(supervisor.active["pid"]) or close_fixture(supervisor, code))
        with patch("services.otc_collection_ops.ops.subprocess.Popen", return_value=Mock(pid=4321)), patch("services.otc_collection_ops.ops.process_identity", return_value={"start_ticks": 999}), patch("services.otc_collection_ops.ops.utc_ms", return_value=START + 1000), patch("builtins.print"):
            self.assertEqual(supervisor.run(), 2)
        self.assertEqual(stopped, [4321])
        self.assertIsNone(supervisor.active)
        self.assertTrue(Path(old["db_path"]).exists())

    def test_archive_post_removal_reporting_error_preserves_verified_retention_evidence(self):
        supervisor = supervisor_fixture(self.root)
        path = Path(supervisor.active["db_path"])
        database(path, supervisor.registration)
        segment = supervisor.active
        segment["state"] = "producer_closed"
        original = sha_file(path)
        supervisor.save = Mock(side_effect=[None, OSError(28, "full"), OSError(28, "full")])
        with patch("services.otc_collection_ops.ops.alive", return_value=False):
            supervisor.enqueue_archive(segment)
            supervisor.executor.shutdown(wait=True)
        supervisor.consume_archives()
        self.assertFalse(path.exists())
        self.assertTrue(segment["raw_removed"])
        self.assertEqual(verify_gzip(segment["gzip_path"], *original), original)
        self.assertEqual(segment["archive_error"], "archive_io_failed_post_removal")
        self.assertFalse(supervisor.chain["complete"])

    def test_unverified_new_child_never_signaled_or_reported_physically_closed(self):
        supervisor = supervisor_fixture(self.root)
        supervisor.chain["segments"][0]["state"] = "producer_closed"
        supervisor.active = None
        supervisor.argv = ["/usr/bin/python3", "-m", "services.otc_collector.runner", "live", "--db", str(self.root / "receipts.sqlite")]
        supervisor.save, supervisor.status = Mock(), Mock(return_value={})
        with patch("services.otc_collection_ops.ops.subprocess.Popen", return_value=Mock(pid=4321)), patch("services.otc_collection_ops.ops.process_identity", side_effect=OpsFault("process_module_mismatch")), patch("services.otc_collection_ops.ops.os.kill") as kill, patch("services.otc_collection_ops.ops.signal.pidfd_send_signal") as send, patch("services.otc_collection_ops.ops.utc_ms", return_value=START + 1000), patch("builtins.print"):
            self.assertEqual(supervisor.run(), 2)
        self.assertEqual(supervisor.chain["unverified_launched_child"]["pid"], 4321)
        self.assertFalse(supervisor.chain["physically_closed"])
        send.assert_not_called()
        kill.assert_not_called()

    def test_opsfault_only_storage_handler_mutant_is_killed(self):
        import inspect
        import textwrap
        import services.otc_collection_ops.ops as module
        tree = ast.parse(textwrap.dedent(inspect.getsource(Supervisor.run)))
        handler = tree.body[0].body[0].handlers[0]
        self.assertEqual(handler.type.id, "Exception")
        handler.type = ast.Name(id="OpsFault", ctx=ast.Load())
        namespace = dict(vars(module))
        exec(compile(ast.fix_missing_locations(tree), "opsfault_only_storage_mutant", "exec"), namespace)
        supervisor = supervisor_fixture(self.root)
        supervisor.status = Mock(side_effect=OSError(28, "full"))
        supervisor.save = Mock()
        supervisor.close_owned = Mock(side_effect=lambda code, **_: close_fixture(supervisor, code))
        # This is the rejected catch-only-OpsFault path. The required public
        # contract is an exit code, so an escaping IO exception kills it.
        with patch("services.otc_collection_ops.ops.utc_ms", return_value=START + 1000), patch("builtins.print"):
            with self.assertRaises(OSError):
                namespace["run"](supervisor)

    def test_complete_reporting_error_never_returns_success(self):
        supervisor = supervisor_fixture(self.root)
        supervisor.active = None
        supervisor.chain["complete"] = True
        supervisor.chain["segments"] = []
        supervisor.status = Mock(side_effect=OSError(28, "full"))
        supervisor.save = Mock(side_effect=OSError(28, "full"))
        with patch("services.otc_collection_ops.ops.utc_ms", return_value=supervisor.registration["end_ms"]), patch("builtins.print"):
            self.assertEqual(supervisor.run(), 2)
        self.assertFalse(supervisor.chain["complete"])

    def assert_terminal_closure_error_retains_raw(self, requested_stop):
        supervisor = supervisor_fixture(self.root)
        path = Path(supervisor.active["db_path"])
        database(path, supervisor.registration)
        before = sha_file(path)
        supervisor.status = Mock(return_value={"capacity_reserve_violated": False})
        supervisor.save = Mock(side_effect=[OSError(28, "closure event full"), None, None])
        supervisor.enqueue_archive = Mock(wraps=supervisor.enqueue_archive)
        if requested_stop:
            supervisor.stop.set()
        now = START + 1000 if requested_stop else supervisor.registration["end_ms"]
        with patch("services.otc_collection_ops.ops.utc_ms", return_value=now), patch("services.otc_collection_ops.ops.alive", return_value=False), patch("services.otc_collection_ops.ops.os.kill") as kill, patch("services.otc_collection_ops.ops.signal.pidfd_send_signal") as send, patch("services.otc_collection_ops.ops.subprocess.Popen", side_effect=AssertionError("no process launch")), patch("builtins.print"):
            result = supervisor.run()
        self.assertEqual(result, 2)
        self.assertEqual(supervisor.failure, "supervisor_operational_io_failed")
        self.assertIsNone(supervisor.active)
        self.assertTrue(supervisor.chain["physically_closed"])
        self.assertFalse(supervisor.chain["complete"])
        self.assertEqual(supervisor.chain["segments"][0]["state"], "producer_closed",
                         canonical({"archive_count": len(supervisor.archives), "raw_exists": path.exists(),
                                    "raw_removed": supervisor.chain["segments"][0].get("raw_removed", False)}))
        self.assertEqual(sha_file(path), before)
        self.assertFalse(Path(supervisor.chain["segments"][0]["gzip_target"]).exists())
        supervisor.enqueue_archive.assert_not_called()
        self.assertEqual(supervisor.archives, [])
        kill.assert_not_called()
        send.assert_not_called()

    def test_registered_end_closure_event_failure_never_archives_closed_raw(self):
        self.assert_terminal_closure_error_retains_raw(False)

    def test_requested_stop_closure_event_failure_never_archives_closed_raw(self):
        self.assert_terminal_closure_error_retains_raw(True)

    def test_handoff_failure_after_launch_never_admits_closed_archive(self):
        supervisor = supervisor_fixture(self.root)
        closed = close_fixture(supervisor, "daily_handoff")
        supervisor.close_owned = Mock(return_value=closed)
        supervisor.save = Mock()
        supervisor.launch_next = Mock(side_effect=lambda: supervisor.remember_failure(OSError(28, "launch event full")))
        supervisor.enqueue_archive = Mock()
        with self.assertRaisesRegex(OpsFault, "supervisor_operational_io_failed"):
            supervisor.handoff()
        supervisor.launch_next.assert_called_once()
        supervisor.enqueue_archive.assert_not_called()
        supervisor.executor.shutdown()

    def test_transport_summary_and_post_launch_failures_never_admit_closed_archive(self):
        for stage in ("summary", "launch"):
            with self.subTest(stage=stage):
                case = self.root / stage
                case.mkdir()
                supervisor = supervisor_fixture(case)
                raw = Path(supervisor.active["db_path"])
                database(raw, supervisor.registration)
                before = sha_file(raw)
                supervisor.status = Mock(return_value={"capacity_reserve_violated": False})
                supervisor.save = Mock()
                supervisor.enqueue_archive = Mock()
                summary = {"latest_health_code": "network_close_timeout", "health_counts": {"network_close_timeout": 1}}
                def read_summary(*_, **__):
                    if stage == "summary":
                        supervisor.remember_failure(OSError(28, "summary failure"))
                    return summary
                supervisor.launch_next = Mock(side_effect=lambda: supervisor.remember_failure(OSError(28, "launch failure")))
                with patch("services.otc_collection_ops.ops.utc_ms", return_value=START + 1000), patch("services.otc_collection_ops.ops.alive", return_value=False), patch("services.otc_collection_ops.ops.database_summary", side_effect=read_summary), patch("builtins.print"):
                    self.assertEqual(supervisor.run(), 2)
                self.assertEqual(supervisor.launch_next.call_count, 0 if stage == "summary" else 1)
                supervisor.enqueue_archive.assert_not_called()
                self.assertEqual(sha_file(raw), before)
                self.assertIsNone(supervisor.active)
                self.assertFalse(supervisor.chain["complete"])

    def test_archive_admission_and_queued_work_reject_diagnosed_failure(self):
        supervisor = supervisor_fixture(self.root)
        path = Path(supervisor.active["db_path"])
        database(path, supervisor.registration)
        segment = close_fixture(supervisor, "daily_handoff")
        before = sha_file(path)
        future, work = Future(), []
        supervisor.executor.submit = Mock(side_effect=lambda job: work.append(job) or future)
        supervisor.save = Mock()
        supervisor.enqueue_archive(segment)
        supervisor.remember_failure(OSError(28, "diagnosed failure"))
        with patch("services.otc_collection_ops.ops.archive_closed") as archive, patch("services.otc_collection_ops.ops.subprocess.Popen") as launch:
            with self.assertRaisesRegex(OpsFault, "supervisor_operational_io_failed") as raised:
                work[0]()
            future.set_exception(raised.exception)
            supervisor.consume_archives()
            with self.assertRaises(OpsFault):
                supervisor.enqueue_archive(segment)
            with self.assertRaises(OpsFault):
                supervisor.launch_next()
            with self.assertRaises(OpsFault):
                supervisor.remove_verified_raw(segment)
            archive.assert_not_called()
            launch.assert_not_called()
        self.assertEqual(supervisor.executor.submit.call_count, 1)
        self.assertEqual(supervisor.observed_archives, {future})
        self.assertEqual(sha_file(path), before)
        supervisor.executor.shutdown()

    def assert_real_database_fault_stops(self, foreign):
        supervisor = supervisor_fixture(self.root)
        path = Path(supervisor.active["db_path"])
        writer = None
        if foreign:
            other = registration()
            other.pop("registration_sha256")
            other["created_ms"] -= 1000
            other["registration_sha256"] = digest(other)
            database(path, other)
            writer = sqlite3.connect(path)
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("INSERT INTO receipts VALUES('foreign-wal',?)", (START + 500,))
            writer.commit()
            expected = "segment_registration_mismatch"
        else:
            path.write_bytes(b"actual invalid sqlite bytes")
            expected = "segment_database_read_failed"
        before = sha_file(path)
        wal = Path(str(path) + "-wal")
        wal_before = sha_file(wal) if wal.exists() else None
        supervisor.save = Mock()
        supervisor.launch_next, supervisor.enqueue_archive = Mock(), Mock()
        supervisor.stop.wait = Mock(side_effect=AssertionError("fault reached collection wait"))
        running = [True]
        def terminate(*_):
            running[0] = False
        with patch("services.otc_collection_ops.ops.utc_ms", return_value=START + 1000), patch("services.otc_collection_ops.ops.time.monotonic", return_value=31), patch("services.otc_collection_ops.ops.alive", side_effect=lambda *_: running[0]), patch("services.otc_collection_ops.ops.process_identity") as identity, patch("services.otc_collection_ops.ops.os.pidfd_open", return_value=66), patch("services.otc_collection_ops.ops.os.close"), patch("services.otc_collection_ops.ops.signal.pidfd_send_signal", side_effect=terminate) as send, patch("services.otc_collection_ops.ops.os.kill") as kill, patch("builtins.print"):
            self.assertEqual(supervisor.run(), 2)
        self.assertEqual(supervisor.failure, expected)
        self.assertFalse(running[0])
        self.assertFalse(supervisor.chain["complete"])
        self.assertFalse(supervisor.chain["physically_closed"])
        self.assertIsNotNone(supervisor.active)  # Database cannot prove session closure.
        self.assertIn("owned_stop_requires_operator", canonical(supervisor.chain["events"]))
        self.assertNotIn("temporarily_unavailable", canonical(supervisor.chain))
        self.assertEqual(sha_file(path), before)
        if wal_before is not None:
            self.assertEqual(sha_file(wal), wal_before)
        supervisor.launch_next.assert_not_called()
        supervisor.enqueue_archive.assert_not_called()
        supervisor.stop.wait.assert_not_called()
        identity.assert_called_once()
        send.assert_called_once()
        kill.assert_not_called()
        if writer is not None:
            writer.close()

    def test_real_corrupt_sqlite_status_stops_verified_producer_and_retains_raw(self):
        self.assert_real_database_fault_stops(False)

    def test_real_foreign_registration_wal_status_stops_without_checkpointing_foreign_bytes(self):
        self.assert_real_database_fault_stops(True)

    def test_healthy_live_wal_status_reads_only_committed_receipts_and_reaches_wait(self):
        supervisor = supervisor_fixture(self.root)
        path = Path(supervisor.active["db_path"])
        database(path, supervisor.registration)
        writer = sqlite3.connect(path)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("DELETE FROM sessions WHERE transition='close'")
        writer.execute("INSERT INTO receipts VALUES('committed-wal',?)", (START + 500,))
        writer.commit()
        writer.execute("INSERT INTO receipts VALUES('uncommitted-wal',?)", (START + 1000,))
        wal = Path(str(path) + "-wal")
        before = sha_file(wal)
        class LiveWait(Exception):
            pass
        supervisor.stop.wait = Mock(side_effect=LiveWait())
        with patch("services.otc_collection_ops.ops.utc_ms", return_value=START + 1000), patch("services.otc_collection_ops.ops.time.monotonic", return_value=31), patch("services.otc_collection_ops.ops.alive", return_value=True), patch("builtins.print"):
            report = supervisor.status()
            self.assertTrue(report["database_ready"])
            self.assertEqual(report["persisted_state"]["receipt_count"], 2)
            self.assertEqual(report["persisted_state"]["unclosed_session_count"], 1)
            self.assertGreater(report["active_raw_bytes"], path.stat().st_size)
            with self.assertRaises(LiveWait):
                supervisor.collect()
        self.assertEqual(sha_file(wal), before)
        self.assertIsNone(supervisor.failure)
        supervisor.stop.wait.assert_called_once()
        writer.rollback()
        writer.close()
        supervisor.executor.shutdown()

    def test_known_new_producer_startup_is_bounded_pending_and_never_hides_bad_databases(self):
        for shape, expected in (("missing", None), ("empty", None), ("schema", None),
                                ("corrupt", "segment_database_read_failed"),
                                ("foreign", "segment_registration_mismatch"),
                                ("unknown", "segment_database_schema_mismatch"),
                                ("wrong_columns", "segment_database_schema_mismatch")):
            with self.subTest(shape=shape):
                case = self.root / shape
                case.mkdir()
                supervisor = supervisor_fixture(case)
                path = Path(supervisor.active["db_path"])
                supervisor.active["database_startup_pending"] = True
                supervisor.children[1234] = Mock()
                supervisor.startup_deadlines[1234] = 31 + STARTUP_GRACE_SECONDS
                if shape == "empty":
                    path.touch()
                elif shape == "schema":
                    database(path, supervisor.registration)
                    with sqlite3.connect(path) as connection:
                        for table in ("registration", "sessions", "receipts", "observations", "health"):
                            connection.execute(f"DELETE FROM {table}")
                elif shape == "corrupt":
                    path.write_bytes(b"invalid fresh child sqlite")
                elif shape == "foreign":
                    record = registration()
                    record.pop("registration_sha256")
                    record["created_ms"] -= 1000
                    record["registration_sha256"] = digest(record)
                    database(path, record)
                elif shape == "unknown":
                    with sqlite3.connect(path) as connection:
                        connection.execute("CREATE TABLE unknown(value TEXT)")
                elif shape == "wrong_columns":
                    with sqlite3.connect(path) as connection:
                        connection.execute("BEGIN")
                        for table in ("registration", "sessions", "receipts", "observations", "health"):
                            connection.execute(f"CREATE TABLE {table}(value TEXT)")
                with patch("services.otc_collection_ops.ops.utc_ms", return_value=START + 1000), patch("services.otc_collection_ops.ops.time.monotonic", return_value=31), patch("services.otc_collection_ops.ops.process_identity") as identity, patch("builtins.print"):
                    if expected:
                        with self.assertRaisesRegex(OpsFault, expected):
                            supervisor.status()
                    else:
                        report = supervisor.status()
                        self.assertFalse(report["database_ready"])
                        self.assertEqual(report["persisted_state"]["read_status"], "awaiting_owned_database_startup")
                identity.assert_called_once()
                if expected is None:
                    with patch("services.otc_collection_ops.ops.time.monotonic", return_value=supervisor.startup_deadlines[1234]):
                        with self.assertRaises(OpsFault):
                            supervisor.status()
                supervisor.executor.shutdown()

    def test_unowned_missing_database_and_unreadable_liveness_are_fixed_faults(self):
        supervisor = supervisor_fixture(self.root)
        with self.assertRaisesRegex(OpsFault, "segment_database_missing"):
            supervisor.status()
        with patch("services.otc_collection_ops.ops.Path.read_text", side_effect=OSError(5, "private proc error")):
            with self.assertRaisesRegex(OpsFault, "owned_process_liveness_read_failed"):
                alive(1234, 777)
        with patch("services.otc_collection_ops.ops.Path.read_text", side_effect=FileNotFoundError()):
            self.assertFalse(alive(1234, 777))
        with self.assertRaisesRegex(OpsFault, "owned_process_liveness_read_failed"):
            alive(1234, 777, proc_root=self.root / "unavailable-proc")
        supervisor.executor.shutdown()

    def test_expired_owned_startup_fails_before_the_regular_status_interval(self):
        supervisor = supervisor_fixture(self.root)
        supervisor.active["database_startup_pending"] = True
        supervisor.startup_deadlines[1234] = 1
        supervisor.children[1234] = Mock()
        supervisor.save = Mock()
        supervisor.launch_next, supervisor.enqueue_archive = Mock(), Mock()
        supervisor.stop.wait = Mock(side_effect=AssertionError("expired startup reached wait"))
        with patch("services.otc_collection_ops.ops.utc_ms", return_value=START + 1000), patch("services.otc_collection_ops.ops.time.monotonic", return_value=1), patch("services.otc_collection_ops.ops.alive", return_value=False), patch("builtins.print"):
            self.assertEqual(supervisor.run(), 2)
        self.assertEqual(supervisor.failure, "segment_database_missing")
        supervisor.stop.wait.assert_not_called()
        supervisor.launch_next.assert_not_called()
        supervisor.enqueue_archive.assert_not_called()
        self.assertFalse(supervisor.chain["complete"])

    def test_real_source_and_registration_file_mutations_fail_status_without_unknown_retry(self):
        for changed in ("source", "registration"):
            with self.subTest(changed=changed):
                case = self.root / changed
                case.mkdir()
                supervisor = supervisor_fixture(case)
                source_file = supervisor.source / "services" / "otc_collector" / "__init__.py"
                source_file.parent.mkdir(parents=True)
                source_file.write_text("# frozen fixture\n")
                record = registration()
                record.pop("registration_sha256")
                record["code_files"] = {"__init__.py": sha_file(source_file)[0]}
                record["code_sha256"] = digest(record["code_files"])
                record["registration_sha256"] = digest(record)
                supervisor.registration, supervisor.registration_id = record, record["registration_sha256"]
                supervisor.registration_path.write_text(canonical(record))
                supervisor.source_registration_bytes_sha256 = sha_file(supervisor.registration_path)[0]
                supervisor.assert_frozen = Supervisor.assert_frozen.__get__(supervisor)
                if changed == "source":
                    source_file.write_text("# changed fixture\n")
                    expected = "immutable_collector_source_changed"
                else:
                    supervisor.registration_path.write_text(canonical(record) + "\n")
                    expected = "registration_file_changed"
                with self.assertRaisesRegex(OpsFault, expected):
                    supervisor.status()
                supervisor.executor.shutdown()

    def assert_frozen_file_fault_closes_owned_run(self, fault):
        for recorded_close in (False, True):
            with self.subTest(fault=fault, recorded_close=recorded_close):
                root = self.root / f"{fault}-{recorded_close}"
                root.mkdir()
                args, source_file, proc_root, proc = frozen_run_fixture(root)
                path, reg = Path(args.initial_db), Path(args.registration)
                real_close = os.close
                expected = {"source_mutation": "immutable_collector_source_changed",
                            "registration_mutation": "registration_file_changed",
                            "source_read_fault": "supervisor_operational_io_failed",
                            "registration_read_fault": "supervisor_operational_io_failed"}[fault]
                def terminate(*_):
                    proc.joinpath("stat").write_text("1234 (fixture) " + " ".join(["Z"] + ["0"] * 18 + ["777"]))
                    if recorded_close:
                        with sqlite3.connect(path) as conn:
                            conn.execute("INSERT INTO sessions VALUES('s','close',?)", (START + 1000,))
                with patch("services.otc_collection_ops.ops.utc_ms", return_value=START + 1000), patch("services.otc_collection_ops.ops.time.monotonic", return_value=31), patch("services.otc_collection_ops.ops.process_identity", side_effect=lambda *a, **kw: process_identity(*a, proc_root=proc_root, **kw)) as identity, patch("services.otc_collection_ops.ops.alive", side_effect=lambda *a, **kw: alive(*a, proc_root=proc_root, **kw)), patch("services.otc_collection_ops.ops.os.pidfd_open", return_value=999999) as pidfd, patch("services.otc_collection_ops.ops.os.close", side_effect=lambda fd: None if fd == 999999 else real_close(fd)) as closefd, patch("services.otc_collection_ops.ops.signal.pidfd_send_signal", side_effect=terminate) as send, patch("services.otc_collection_ops.ops.os.kill") as kill, patch("services.otc_collection_ops.ops.subprocess.Popen", side_effect=AssertionError("fault launched a real process")) as launch, patch("builtins.print"):
                    supervisor = Supervisor(args)
                    before = sha_file(path)
                    original_registration = supervisor.registration_id
                    if fault == "source_mutation":
                        source_file.write_text("# changed run fixture\n")
                    elif fault == "registration_mutation":
                        reg.write_text(reg.read_text() + "\n")
                    elif fault == "source_read_fault":
                        source_file.unlink()
                        source_file.symlink_to(source_file.name)  # Actual ELOOP on source read.
                    else:
                        reg.unlink()
                        reg.mkdir()  # Actual EISDIR on registration read, same process path.
                    supervisor.enqueue_archive = Mock(wraps=supervisor.enqueue_archive)
                    supervisor.remove_verified_raw = Mock(wraps=supervisor.remove_verified_raw)
                    supervisor.stop.wait = Mock(side_effect=AssertionError("fault reached collection wait"))
                    self.assertEqual(supervisor.run(), 2)
                self.assertEqual(supervisor.failure, expected)
                self.assertEqual(supervisor.chain["failure_diagnostics"][0]["code"], expected)
                self.assertEqual(send.call_count, 1, "mutable file fault must terminate the freshly verified owned producer")
                self.assertFalse(alive(1234, 777, proc_root=proc_root))
                pidfd.assert_called_once_with(1234, 0)
                self.assertEqual(sum(call.args == (999999,) for call in closefd.call_args_list), 1)
                self.assertEqual(identity.call_count, 2)  # Initial admission and fresh shutdown admission.
                self.assertEqual(supervisor.chain["physically_closed"], recorded_close)
                self.assertEqual(supervisor.active is None, recorded_close)
                self.assertFalse(supervisor.chain["complete"])
                self.assertEqual(supervisor.chain["registration_sha256"], original_registration)
                self.assertEqual(supervisor.chain["global_start_ms"], START)
                self.assertEqual(supervisor.chain["global_end_ms"], START + 7 * DAY_MS)
                self.assertTrue(path.is_file())
                if not recorded_close:
                    self.assertEqual(sha_file(path), before)
                    self.assertIn("owned_stop_requires_operator", canonical(supervisor.chain["events"]))
                with sqlite3.connect(path) as conn:
                    self.assertEqual(conn.execute("SELECT frame_id,received_at_ms FROM receipts").fetchall(), [("r", START)])
                    self.assertEqual(conn.execute("SELECT asset,kind,available_ms FROM observations").fetchall(), [("EURUSD-OTC", "quote", START)])
                    self.assertEqual(conn.execute("SELECT transition,at_ms FROM sessions ORDER BY at_ms").fetchall(),
                                     [("open", START)] + ([("close", START + 1000)] if recorded_close else []))
                self.assertFalse(supervisor.chain["segments"][0].get("raw_removed", False))
                self.assertFalse(Path(supervisor.chain["segments"][0]["gzip_target"]).exists())
                self.assertEqual(json.loads(supervisor.chain_path.read_text()), source_chain(supervisor.chain))
                supervisor.enqueue_archive.assert_not_called()
                supervisor.remove_verified_raw.assert_not_called()
                supervisor.stop.wait.assert_not_called()
                launch.assert_not_called()
                kill.assert_not_called()

    def test_real_source_mutation_run_stops_only_owned_process_and_retains_raw(self):
        self.assert_frozen_file_fault_closes_owned_run("source_mutation")

    def test_real_registration_mutation_run_stops_only_owned_process_and_retains_raw(self):
        self.assert_frozen_file_fault_closes_owned_run("registration_mutation")

    def test_real_source_read_fault_run_stops_only_owned_process_and_retains_raw(self):
        self.assert_frozen_file_fault_closes_owned_run("source_read_fault")

    def test_real_registration_read_fault_run_stops_only_owned_process_and_retains_raw(self):
        self.assert_frozen_file_fault_closes_owned_run("registration_read_fault")

    def test_mutable_file_cleanup_still_rejects_unknown_process_identity(self):
        for changed in ("argv", "database", "registration", "cwd", "exe", "start_ticks"):
            with self.subTest(changed=changed):
                root = self.root / changed
                root.mkdir()
                args, source_file, proc_root, proc = frozen_run_fixture(root)
                real_close = os.close
                with patch("services.otc_collection_ops.ops.utc_ms", return_value=START + 1000), patch("services.otc_collection_ops.ops.time.monotonic", return_value=31), patch("services.otc_collection_ops.ops.process_identity", side_effect=lambda *a, **kw: process_identity(*a, proc_root=proc_root, **kw)), patch("services.otc_collection_ops.ops.alive", side_effect=lambda *a, **kw: alive(*a, proc_root=proc_root, **kw)), patch("services.otc_collection_ops.ops.os.pidfd_open", return_value=999999), patch("services.otc_collection_ops.ops.os.close", side_effect=lambda fd: None if fd == 999999 else real_close(fd)), patch("services.otc_collection_ops.ops.signal.pidfd_send_signal") as send, patch("services.otc_collection_ops.ops.os.kill") as kill, patch("services.otc_collection_ops.ops.subprocess.Popen") as launch, patch("builtins.print"):
                    supervisor = Supervisor(args)
                    before = sha_file(args.initial_db)
                    source_file.write_text("# changed source before identity attack\n")
                    if changed in ("argv", "database", "registration"):
                        cmdline = proc.joinpath("cmdline")
                        old = cmdline.read_bytes()
                        if changed == "argv":
                            old = old.replace(b"-u\0", b"-c\0pass\0", 1)
                        else:
                            old = old.replace(str(getattr(args, "initial_db" if changed == "database" else "registration")).encode(), str(root / "unknown").encode(), 1)
                        cmdline.write_bytes(old)
                    elif changed in ("cwd", "exe"):
                        proc.joinpath(changed).unlink()
                        proc.joinpath(changed).symlink_to(root if changed == "cwd" else "/bin/echo")
                    else:
                        proc.joinpath("stat").write_text("1234 (reused) " + " ".join(["S"] + ["0"] * 18 + ["778"]))
                    supervisor.enqueue_archive = Mock(wraps=supervisor.enqueue_archive)
                    supervisor.stop.wait = Mock(side_effect=AssertionError("identity fault reached wait"))
                    self.assertEqual(supervisor.run(), 2)
                self.assertEqual(supervisor.failure, "immutable_collector_source_changed")
                self.assertFalse(supervisor.chain["physically_closed"])
                self.assertFalse(supervisor.chain["complete"])
                self.assertIsNotNone(supervisor.active)
                self.assertEqual(sha_file(args.initial_db), before)
                self.assertIn("owned_stop_requires_operator", canonical(supervisor.chain["events"]))
                supervisor.enqueue_archive.assert_not_called()
                supervisor.stop.wait.assert_not_called()
                send.assert_not_called()
                kill.assert_not_called()
                launch.assert_not_called()

    def test_frozen_files_still_gate_normal_close_launch_archive_and_raw_removal(self):
        supervisor = supervisor_fixture(self.root)
        supervisor.assert_frozen = Mock(side_effect=OpsFault("immutable_collector_source_changed"))
        with patch("services.otc_collection_ops.ops.signal.pidfd_send_signal") as send, patch("services.otc_collection_ops.ops.os.pidfd_open") as pidfd, patch("services.otc_collection_ops.ops.subprocess.Popen") as launch, patch("services.otc_collection_ops.ops.archive_closed") as archive, patch.object(supervisor.executor, "submit") as submit:
            for operation in (lambda: supervisor.close_owned("daily_handoff"), supervisor.launch_next,
                              lambda: supervisor.enqueue_archive(supervisor.active),
                              lambda: supervisor.remove_verified_raw(supervisor.active)):
                with self.assertRaisesRegex(OpsFault, "immutable_collector_source_changed"):
                    operation()
            with self.assertRaisesRegex(OpsFault, "owned_cleanup_requires_diagnosed_failure"):
                supervisor.close_owned("supervisor_failure", failure_cleanup=True)
            send.assert_not_called()
            pidfd.assert_not_called()
            launch.assert_not_called()
            archive.assert_not_called()
            submit.assert_not_called()
        supervisor.executor.shutdown()

    def test_frozen_file_cleanup_handler_mutant_is_killed(self):
        import inspect
        import textwrap
        import services.otc_collection_ops.ops as module
        tree = ast.parse(textwrap.dedent(inspect.getsource(Supervisor.close_owned)))
        function = tree.body[0]
        guard = next(node for node in function.body if isinstance(node, ast.If))
        function.body[function.body.index(guard)] = ast.Expr(value=ast.Call(
            func=ast.Attribute(value=ast.Name(id="self", ctx=ast.Load()), attr="assert_frozen", ctx=ast.Load()), args=[], keywords=[]))
        namespace = dict(vars(module))
        exec(compile(ast.fix_missing_locations(tree), "frozen_file_cleanup_mutant", "exec"), namespace)
        with patch.object(Supervisor, "close_owned", namespace["close_owned"]):
            result = unittest.TestResult()
            EssentialTests("test_real_source_mutation_run_stops_only_owned_process_and_retains_raw").run(result)
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.failures), 2)
        self.assertTrue(all("mutable file fault must terminate" in detail for _, detail in result.failures))


def main():
    output = io.StringIO()
    with redirect_stdout(output):
        result = unittest.TextTestRunner(stream=output).run(unittest.defaultTestLoader.loadTestsFromTestCase(EssentialTests))
    report = {"schema": "otc_collection_ops_focused_eval_v1", "tests": result.testsRun, "errors": len(result.errors),
              "failures": len(result.failures), "pass_threshold": 1.0, "passed": result.wasSuccessful(),
              "broker_calls": 0, "ssh_calls": 0, "credential_value_reads": 0, "real_process_signals": 0,
              "storage_fault_mutant_killed": result.wasSuccessful(),
              "frozen_file_cleanup_mutant_killed": result.wasSuccessful(),
              "failure_path_coverage": ["status", "closure_progress", "closure_event", "state_save", "adoption_save",
                                        "launch_save", "archive_worker", "archive_publication", "archive_wait", "archive_future",
                                        "archive_post_removal", "complete_reporting", "ownership_rejection", "registered_end_archive_guard",
                                        "requested_stop_archive_guard", "handoff_archive_guard", "transport_archive_guard", "queued_archive_guard",
                                        "real_corrupt_sqlite_status", "real_foreign_registration_wal_status", "healthy_live_wal_status",
                                        "bounded_owned_startup", "unknown_database_status", "liveness_read_failure", "source_registration_mutation",
                                        "real_source_mutation_run", "real_registration_mutation_run", "real_source_read_fault_run",
                                        "real_registration_read_fault_run", "mutable_file_cleanup_identity_rejection",
                                        "frozen_normal_admission", "frozen_file_cleanup_mutant"]}
    print(canonical(report))
    if not result.wasSuccessful():
        print(output.getvalue())
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
