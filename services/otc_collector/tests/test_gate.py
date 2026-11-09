"""Attacker-oriented receipt, schedule, persistence, privacy, and transport regression gates."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from services.otc_collector.adapter import Adapter, InvalidFrame, Receipt, allowed_outgoing, subscriptions, SNAPSHOT
from services.otc_collector.collector import Collector, CollectorHalted
from services.otc_collector.export import freeze
from services.otc_collector.monitor import progress
from services.otc_collector.protocol import CONFIG, DAY_MS, canonical, digest, make_registration, validate_registration
from services.otc_collector.runner import main, authenticate, credentials, TransportFault, send_read, AUTH_URL
from services.otc_collector.store import Store, IdentityConflict, StorageFault
from services.otc_collector.tests.support import START, START_TEXT, RESEARCH_ROOT, registered, setup, temporary, quote, snapshot


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = Adapter()
        self.receipt = Receipt("session", 1, START, 1_000_000_000)
        self.adapter.parse(canonical({"name": "timeSync", "msg": START}), self.receipt)
    def parse(self, frame):
        return self.adapter.parse(canonical(frame), self.receipt)
    def test_one_top_level_quote_per_actual_all_size_frame(self):
        result = self.parse(quote())
        self.assertEqual(len(result["events"]), 1)
        obs = result["events"][0]["observation"]
        self.assertEqual(obs["value"], "1.15")
        self.assertEqual(obs["available_ms"], START)
        self.assertEqual(obs["event_ms"], START)
        self.assertEqual(result["events"][0]["lineage"]["source_event_ms"], START)
        self.assertEqual(obs["clock_id"], "receiver_utc")
    def test_decimal_midpoint_under_hostile_ambient_precision(self):
        from decimal import localcontext
        raw = '{"name":"candles-generated","msg":{"active_id":76,"at":1893456000000,"bid":1.123456789012345678901,"ask":1.123456789012345678903}}'
        with localcontext() as ctx:
            ctx.prec = 3
            event = self.adapter.parse(raw, self.receipt)["events"][0]
        self.assertEqual(event["observation"]["value"], "1.123456789012345678902")
    def test_rejects_nonfinite_boolean_negative_crossed_and_wrong_assets(self):
        variants = []
        for field, bad in (("bid", True), ("bid", -1), ("ask", 1.0), ("active_id", True), ("active_id", 1), ("at", True), ("bid", "1.1")):
            value = quote()
            value["msg"][field] = bad
            variants.append(canonical(value))
        variants.extend(['{"name":"candles-generated","msg":{"bid":NaN}}', '{"name":"candles-generated","msg":{"bid":Infinity}}'])
        for raw in variants:
            with self.subTest(raw=raw), self.assertRaises(InvalidFrame):
                self.adapter.parse(raw, self.receipt)
    def test_json_duplicate_fields_rejected(self):
        with self.assertRaisesRegex(InvalidFrame, "duplicate_json_field"):
            self.adapter.parse('{"name":"profile","name":"candles-generated"}', self.receipt)
    def test_personal_unknown_frames_not_persistable(self):
        for name in ("profile", "ssid", "order", "unexpected-private-frame"):
            self.assertIsNone(self.parse({"name": name, "msg": {"email": "SECRET", "password": "SECRET"}}))
    def test_mood_scope_assumption_is_explicit(self):
        event = self.parse({"name": "traders-mood-changed", "msg": {"asset_id": 76, "value": 0.61}})["events"][0]
        self.assertEqual(event["observation"]["value"], "0.61")
        self.assertEqual(event["lineage"]["product_basis"], "subscription_scope_assumed")
        with self.assertRaisesRegex(InvalidFrame, "wrong_product"):
            self.parse({"name": "traders-mood-changed", "msg": {"asset_id": 76, "value": 0.61, "instrument": "digital-option"}})
        with self.assertRaisesRegex(InvalidFrame, "wrong_product"):
            self.parse({"name": "traders-mood-changed", "msg": {"asset_id": 76, "value": 0.61, "instrument": "turbo-option", "instrument_type": "digital-option"}})
    def test_commission_strict_shape_and_semantics(self):
        base = {"name": "commission-changed", "msg": {"active_id": 76, "instrument_type": "turbo-option", "commission": {"value": 18}}}
        event = self.parse(base)["events"][0]
        self.assertEqual(event["observation"]["value"], "0.82")
        self.assertEqual(event["observation"]["source"], "commission-stream")
        for bad in ({"value": 18, "unit": "percent"}, 18, {"value": True}, {"value": -1}, {"value": 101}):
            frame = copy.deepcopy(base)
            frame["msg"]["commission"] = bad
            with self.assertRaises(InvalidFrame):
                self.parse(frame)
    def test_snapshot_valid_and_unsupported_offer_fail_closed(self):
        result = self.parse(snapshot())
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual({e["observation"]["source"] for e in result["events"]}, {"init-snapshot"})
        bad = snapshot()
        bad["msg"]["result"]["turbo"]["actives"]["76"]["is_suspended"] = True
        with self.assertRaisesRegex(InvalidFrame, "unsupported_offer_state"):
            self.parse(bad)
    def test_clock_unsynchronized_stale_and_offset_preserved(self):
        fresh = Adapter()
        event = fresh.parse(canonical(quote()), self.receipt)["events"][0]
        self.assertEqual(event["lineage"]["clock_status"], "clock_unsynchronized")
        receipt = Receipt("session", 2, START + 60_001, 61_001_000_000)
        self.assertEqual(self.adapter.parse(canonical(quote(at=receipt.received_at_ms)), receipt)["events"][0]["lineage"]["clock_status"], "clock_sync_stale")
    def test_outgoing_allowlist_has_no_trade_or_account_operations(self):
        for permitted in [*subscriptions(), SNAPSHOT, {"name": "ssid", "msg": "synthetic-token"}]:
            self.assertTrue(allowed_outgoing(permitted))
        for rejected in ({"name": "buyv3", "msg": {}}, {"name": "changebalance", "msg": {}},
                         {"name": "sendMessage", "msg": {"name": "get-positions"}},
                         {"name": "api_option_init_all", "msg": "", "request_id": "bad"}):
            self.assertFalse(allowed_outgoing(rejected))


class RegistrationTests(unittest.TestCase):
    def test_frozen_phases_expiry_ages_and_code(self):
        reg = registered()
        self.assertEqual(reg["end_ms"] - reg["start_ms"], 7 * DAY_MS)
        self.assertEqual([p["end_ms"] - p["start_ms"] for p in reg["phases"]], [3*DAY_MS, DAY_MS, DAY_MS, DAY_MS, DAY_MS])
        self.assertEqual(reg["config"], CONFIG)
        self.assertEqual(reg["grid_ms"], 120_000)
        self.assertEqual(reg["config_sha256"], digest(CONFIG))
        self.assertEqual(reg["created_ms"], reg["registered_at_ms"])
        self.assertEqual(list(reg["partitions"]), ["train", "early", "calibration", "policy", "diagnostic_test"])
        self.assertEqual(set(reg["source_hashes"]), {"collector", "research"})
        validate_registration(reg)
    def test_registration_rejects_nonfuture_naive_off_grid_or_changed(self):
        for start in ("2030-01-01T00:00:00", "2030-01-01T00:00:01Z", "2020-01-01T00:00:00Z"):
            with self.assertRaises(ValueError):
                make_registration(start, now_ms=START-1)
        reg = registered()
        reg["end_ms"] += 1
        with self.assertRaises(ValueError):
            validate_registration(reg)
    def test_live_cli_ack_precedes_credentials_and_network(self):
        with patch("services.otc_collector.runner.credentials") as credentials, patch("services.otc_collector.runner.authenticate") as connect, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(["live", "--registration", "missing", "--db", "missing", "--env-file", "missing", "--progress-log", "missing"])
            credentials.assert_not_called()
            connect.assert_not_called()
    def test_changed_collector_or_research_source_rejected(self):
        reg = registered()
        changed = dict(reg["code_files"])
        changed["adapter.py"] = "0" * 64
        with patch("services.otc_collector.protocol.code_manifest", return_value=changed), self.assertRaises(ValueError):
            validate_registration(reg)


class TransportTests(unittest.TestCase):
    def test_established_env_keys_are_exact_with_synthetic_reader(self):
        import types
        synthetic = "/tmp/binary-training/collector-variants/B/synthetic-env"
        stat = types.SimpleNamespace(st_mode=0o100600, st_size=128)
        with patch.object(Path, "stat", return_value=stat), patch.object(Path, "read_text", return_value="IQ_EMAIL=synthetic-email\nIQ_PASSWORD=synthetic-password\n"):
            self.assertEqual(credentials(synthetic), ("synthetic-email", "synthetic-password"))
        with patch.object(Path, "stat", return_value=stat), patch.object(Path, "read_text", return_value="IQOPTION_EMAIL=synthetic-email\nIQOPTION_PASSWORD=synthetic-password\n"):
            with self.assertRaisesRegex(ValueError, "IQ_EMAIL and IQ_PASSWORD"):
                credentials(synthetic)
    def test_relative_credentials_are_rejected_before_file_access(self):
        with patch.object(Path, "read_text") as read:
            with self.assertRaisesRegex(ValueError, "absolute"):
                credentials("relative.env")
            read.assert_not_called()
    def test_cookie_auth_finite_tls_no_redirect_with_no_real_credential_reads(self):
        import types
        class Session:
            def __init__(self):
                self.calls = []
                self.closed = False
            def post(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return types.SimpleNamespace(status_code=200, cookies={"ssid": "synthetic-cookie"})
            def close(self):
                self.closed = True
        session = Session()
        with patch.dict("sys.modules", {"requests": types.SimpleNamespace(Session=Session)}), patch("services.otc_collector.runner.credentials", return_value=("synthetic-email", "synthetic-password")):
            result = authenticate("unused", session_factory=lambda: session)
        self.assertEqual(result, "synthetic-cookie")
        self.assertTrue(session.closed)
        self.assertEqual(session.calls[0][0], AUTH_URL)
        self.assertEqual(session.calls[0][1]["timeout"], 10)
        self.assertIs(session.calls[0][1]["verify"], True)
        self.assertIs(session.calls[0][1]["allow_redirects"], False)
        self.assertIs(session.trust_env, False)
    def test_broker_error_cannot_echo_credentials(self):
        import types
        class Session:
            def post(self, *args, **kwargs):
                raise OSError("SYNTHETIC_PRIVATE_PASSWORD")
            def close(self):
                pass
        with patch.dict("sys.modules", {"requests": types.SimpleNamespace(Session=Session)}), patch("services.otc_collector.runner.credentials", return_value=("synthetic", "synthetic")):
            with self.assertRaisesRegex(TransportFault, "authentication_transport_failed") as caught:
                authenticate("unused")
        self.assertNotIn("SYNTHETIC_PRIVATE_PASSWORD", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)


class StorageAndCollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = temporary()
        self.store, self.collector, self.clock = setup(self.tmp.name)
    def tearDown(self):
        if not self.store.failed:
            self.collector.close()
        try:
            self.store.close()
        except sqlite3.Error:
            pass
        self.tmp.cleanup()
    def feed(self, frame):
        self.collector.on_message(None, canonical(frame))
        self.clock.step()
    def count(self, table):
        return self.store.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    def test_repeated_values_are_distinct_real_receipts_no_cache_repetition(self):
        self.feed({"name": "timeSync", "msg": START})
        self.feed(quote())
        self.feed(quote())
        self.assertEqual(self.count("observations"), 2)
        self.assertEqual(self.count("receipts"), 3)
    def test_exact_id_duplicate_idempotent_conflict_halts(self):
        envelope = Adapter().parse(canonical(quote()), Receipt(self.collector.session_id, 100, START, 1))
        self.assertTrue(self.store.append(envelope))
        self.assertFalse(self.store.append(envelope))
        changed = copy.deepcopy(envelope)
        changed["events"][0]["observation"]["value"] = "2"
        with self.assertRaisesRegex(IdentityConflict, "conflicting"):
            self.store.append(changed)
        self.assertTrue(self.store.failed)
        self.assertEqual(self.count("observations"), 1)
    def test_append_only_enforced_in_database(self):
        self.feed(quote())
        for table in ("registration", "receipts", "observations", "sessions", "health"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.store.connection.execute(f"DELETE FROM {table}")
            self.store.connection.rollback()
    def test_quote_receipt_captured_before_json_parse(self):
        original = self.collector.adapter.parse
        def parse(raw, receipt):
            self.clock.step(50)
            return original(raw, receipt)
        self.collector.adapter.parse = parse
        self.feed(quote())
        observed = json.loads(self.store.connection.execute("SELECT observation_json FROM observations").fetchone()[0])
        self.assertEqual(observed["available_ms"], START)
    def test_privacy_stripped_even_from_valid_quote_payload(self):
        self.feed({"name": "profile", "msg": {"email": "DO_NOT_PERSIST", "ssid": "DO_NOT_PERSIST"}})
        frame = quote()
        frame["msg"]["user_id"] = "DO_NOT_PERSIST"
        self.feed(frame)
        self.assertEqual(self.count("receipts"), 1)
        self.assertNotIn("DO_NOT_PERSIST", str(list(self.store.connection.iterdump())))
    def test_both_clock_jump_directions_halt(self):
        self.feed(quote())
        self.clock.wall += 10_000
        with self.assertRaisesRegex(CollectorHalted, "receiver_clock_jump"):
            self.feed(quote())
        self.assertTrue(self.collector.stop.is_set())
        self.assertEqual(self.count("observations"), 1)
    def test_reconnect_sessions_and_resynchronization(self):
        self.feed({"name": "timeSync", "msg": START})
        self.feed(quote())
        old = self.collector.session_id
        self.collector.reconnect()
        self.assertNotEqual(old, self.collector.session_id)
        self.feed(quote())
        self.assertEqual(self.count("observations"), 2)
        states = [r[0] for r in self.store.connection.execute("SELECT clock_status FROM observations ORDER BY rowid")]
        self.assertEqual(states, ["ok", "clock_unsynchronized"])
        self.assertEqual(self.count("sessions"), 3)
    def test_queue_overflow_stops_with_evidence(self):
        self.collector.asynchronous = True
        self.collector.queue = __import__("queue").Queue(maxsize=1)
        self.feed(quote())
        with self.assertRaisesRegex(CollectorHalted, "queue_overflow"):
            self.feed(quote())
        self.assertEqual(self.collector.halt_code, "queue_overflow")
        self.assertIn("queue_overflow", [r[0] for r in self.store.connection.execute("SELECT code FROM health")])
        self.collector.asynchronous = False
    def test_storage_fault_halts_and_writes_safe_marker(self):
        self.store.connection.close()
        with self.assertRaisesRegex(CollectorHalted, "storage_write_failure"):
            self.feed(quote())
        self.assertTrue(self.collector.stop.is_set())
        marker = self.store.path.with_name(self.store.path.name + ".failure.jsonl")
        self.assertTrue(marker.exists())
        self.assertNotIn("bid", marker.read_text())
    def test_process_lock_blocks_parallel_writer(self):
        with self.assertRaisesRegex(StorageFault, "another_collector"):
            Store(self.store.path, registered())
    def test_incompatible_historic_database_not_modified(self):
        historic = Path(self.tmp.name) / "historic.sqlite"
        conn = sqlite3.connect(historic)
        conn.execute("CREATE TABLE quote_samples(value TEXT)")
        conn.commit()
        conn.close()
        before = historic.read_bytes()
        with self.assertRaisesRegex(IdentityConflict, "not_a_fresh"):
            Store(historic, registered())
        self.assertEqual(historic.read_bytes(), before)
    def test_monitor_gap_metrics_and_consistent_freeze(self):
        self.feed({"name": "timeSync", "msg": START})
        self.feed(quote())
        self.clock.step(10_000)
        self.feed(quote(at=self.clock.wall))
        report = progress(self.store.path, START + 12_000)
        stats = report["assets"]["EURUSD-OTC"]
        self.assertEqual(stats["quotes"], 2)
        self.assertEqual(stats["internal_gap_count"], 1)
        self.assertEqual(report["assets"]["GBPUSD-OTC"]["quotes"], 0)
        manifest = freeze(self.store.path, Path(self.tmp.name) / "export")
        self.assertEqual(manifest["observation_count"], 2)
        self.assertEqual(manifest["admissible_clock_observation_count"], 2)


class RestartTests(unittest.TestCase):
    def test_crash_recovery_and_changed_registration_rejection(self):
        with temporary() as directory:
            store, collector, clock = setup(directory)
            collector.on_message(None, canonical(quote()))
            path = store.path
            store.close()  # Model a process exit without session-close journal.
            recovered = Store(path, registered())
            second = Collector(recovered, wall_clock=clock.utc, monotonic_clock=clock.monotonic)
            self.assertIn("partial_crash_recovery", [r[0] for r in recovered.connection.execute("SELECT code FROM health")])
            second.close()
            recovered.close()
            changed = make_registration("2030-01-02T00:00:00Z", now_ms=START-60_000, research_source_root=RESEARCH_ROOT)
            with self.assertRaisesRegex(IdentityConflict, "registration_resume_mismatch"):
                Store(path, changed)


if __name__ == "__main__":
    unittest.main()
