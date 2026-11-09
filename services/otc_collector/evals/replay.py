"""Offline wire replay oracle. No network, credentials, model calls, or historical mutation."""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import time
import unittest
from unittest.mock import patch

from services.otc_collector.adapter import Adapter
from services.otc_collector.collector import Collector, CollectorHalted
from services.otc_collector.export import freeze
from services.otc_collector.monitor import progress
from services.otc_collector.protocol import canonical
from services.otc_collector.store import Store, IdentityConflict
from services.otc_collector.tests.support import START, setup, temporary, quote, snapshot, registered
from services.otc_collector.tests.test_gate import AdapterTests

THRESHOLD = 1.0


def evaluate():
    started = time.perf_counter()
    results = {}
    details = {}
    with temporary() as directory:
        store, collector, clock = setup(directory)
        expected = {"quote": 0, "mood": 0, "payout": 0}
        expected_receipts = 0
        expected_quarantine = 0
        private_marker = "private-eval-marker-DO-NOT-PERSIST"
        def feed(frame, *, received_step=0):
            if received_step:
                clock.step(received_step)
            collector.on_message(None, canonical(frame))
        for tick in range(121):
            if tick:
                clock.step(500)
            if tick % 60 == 0:
                feed({"name": "timeSync", "msg": clock.wall})
                expected_receipts += 1
            for active in (76, 81):
                if not (active == 81 and 30 <= tick < 60):
                    frame = quote(active=active, at=clock.wall)
                    frame["msg"]["email"] = private_marker
                    feed(frame)
                    expected["quote"] += 1
                    expected_receipts += 1
                if tick % 30 == 0:
                    feed({"name": "traders-mood-changed", "msg": {"asset_id": active, "value": 0.6}})
                    expected["mood"] += 1
                    expected_receipts += 1
                if tick % 60 == 0:
                    feed({"name": "commission-changed", "msg": {"active_id": active, "instrument_type": "turbo-option", "commission": {"value": 18}}})
                    expected["payout"] += 1
                    expected_receipts += 1
            if tick % 60 == 0:
                feed(snapshot())
                expected["payout"] += 2
                expected_receipts += 1
        faults = []
        for field, value in (("bid", True), ("bid", -1), ("ask", 1), ("active_id", 1), ("at", False)):
            bad = quote(at=clock.wall)
            bad["msg"][field] = value
            faults.append(bad)
        faults.extend([
            {"name": "traders-mood-changed", "msg": {"asset_id": 76, "value": True}},
            {"name": "traders-mood-changed", "msg": {"asset_id": 76, "value": 0.6, "instrument_type": "digital-option"}},
            {"name": "commission-changed", "msg": {"active_id": 76, "instrument_type": "turbo-option", "commission": {"value": 18, "unit": "percent"}}},
        ])
        bad = snapshot()
        bad["msg"]["result"]["turbo"]["actives"]["81"]["is_suspended"] = True
        faults.append(bad)
        for bad in faults:
            feed(bad)
            expected_quarantine += 1
            expected_receipts += 1
        for name in ("profile", "order", "unknown-private"):
            feed({"name": name, "msg": {"email": private_marker, "ssid": private_marker}})
        collector.on_message(None, '{"name":"candles-generated","msg":{"bid":NaN}}')
        expected_quarantine += 1
        expected_receipts += 1
        actual = dict(store.connection.execute("SELECT kind,count(*) FROM observations GROUP BY kind"))
        results["exact_valid_event_counts"] = actual == expected
        actual_receipts = store.connection.execute("SELECT count(*) FROM receipts").fetchone()[0]
        results["one_receipt_per_permitted_frame"] = actual_receipts == expected_receipts
        quarantine = store.connection.execute("SELECT count(*) FROM health WHERE code='frame_quarantine'").fetchone()[0]
        results["fault_detection_exact_count"] = quarantine == expected_quarantine
        report = progress(store.path, START + 60_000)
        results["injected_gap_detected_for_correct_asset"] = (report["assets"]["GBPUSD-OTC"]["internal_gap_count"] == 1 and report["assets"]["EURUSD-OTC"]["internal_gap_count"] == 0)
        results["gap_does_not_shift_registration"] = store.registration == registered()
        raw = str(list(store.connection.iterdump()))
        results["privacy_marker_absent_from_database"] = private_marker not in raw
        joined = store.connection.execute("SELECT r.received_at_ms,r.monotonic_ns,o.observation_json,o.lineage_json FROM observations o JOIN receipts r USING(frame_id)").fetchall()
        lineage_checks = []
        for receipt_ms, mono, obs_json, meta_json in joined:
            obs, meta = json.loads(obs_json), json.loads(meta_json)
            lineage_checks.append(obs["available_ms"] == receipt_ms == obs["event_ms"] == meta["received_at_ms"] and obs["clock_id"] == "receiver_utc" and meta["monotonic_ns"] == mono and meta["clock_status"] == "ok")
        results["causal_lineage_for_every_event"] = all(lineage_checks) and len(joined) == sum(expected.values())
        first = json.loads(store.connection.execute("SELECT envelope_json FROM receipts ORDER BY rowid LIMIT 1").fetchone()[0])
        results["idempotence_exact_duplicate"] = store.append(first) is False
        exported = Path(directory) / "export"
        manifest = freeze(store.path, exported)
        results["export_counts_and_complete_clock_admission"] = manifest["observation_count"] == sum(expected.values()) == manifest["admissible_clock_observation_count"]
        results["export_hashes_match_bytes"] = all(hashlib.sha256((exported / name).read_bytes()).hexdigest() == value for name, value in manifest["hashes"].items())
        results["privacy_marker_absent_from_export"] = all(private_marker.encode() not in file.read_bytes() for file in exported.iterdir())
        details["replay"] = {"expected_events": expected, "actual_events": actual, "expected_receipts": expected_receipts,
                             "actual_receipts": actual_receipts, "quarantined_frames": quarantine,
                             "gap_coverage": report["assets"], "manifest_sha256": manifest["manifest_sha256"]}
        collector.close()
        store.close()
    for sign in (-1, 1):
        with temporary() as directory:
            store, collector, clock = setup(directory)
            collector.on_message(None, canonical(quote()))
            clock.wall += sign * 10_000
            caught = False
            try:
                collector.on_message(None, canonical(quote()))
            except CollectorHalted:
                caught = collector.halt_code == "receiver_clock_jump"
            results[f"clock_jump_{sign}_fail_closed"] = caught and store.connection.execute("SELECT count(*) FROM observations").fetchone()[0] == 1
            collector.close()
            store.close()
    with temporary() as directory:
        store, collector, clock = setup(directory)
        collector.on_message(None, canonical(quote()))
        first_session = collector.session_id
        collector.reconnect()
        collector.on_message(None, canonical({"name": "timeSync", "msg": clock.wall}))
        collector.on_message(None, canonical(quote()))
        results["reconnect_preserves_and_distinguishes_receipts"] = first_session != collector.session_id and store.connection.execute("SELECT count(DISTINCT frame_id) FROM observations").fetchone()[0] == 2
        store.close()  # Unclosed-session recovery is an explicit failure signal.
        store = Store(Path(directory) / "fresh.sqlite", registered())
        collector = Collector(store, wall_clock=clock.utc, monotonic_clock=clock.monotonic)
        results["restart_partial_recovery_detected"] = store.connection.execute("SELECT count(*) FROM health WHERE code='partial_crash_recovery'").fetchone()[0] == 1
        collector.close()
        store.close()
    with temporary() as directory:
        store, collector, clock = setup(directory)
        collector.on_message(None, canonical(quote()))
        envelope = json.loads(store.connection.execute("SELECT envelope_json FROM receipts ORDER BY rowid LIMIT 1").fetchone()[0])
        envelope["events"][0]["observation"]["value"] = "9"
        caught = False
        try:
            store.append(envelope)
        except IdentityConflict:
            caught = store.failed
        results["conflicting_identity_fail_closed"] = caught and store.connection.execute("SELECT count(*) FROM observations").fetchone()[0] == 1
        store.close()
    with temporary() as directory:
        store, collector, clock = setup(directory)
        collector.asynchronous = True
        collector.queue = __import__("queue").Queue(maxsize=1)
        collector.on_message(None, canonical(quote()))
        caught = False
        try:
            collector.on_message(None, canonical(quote()))
        except CollectorHalted:
            caught = collector.halt_code == "queue_overflow"
        results["queue_overflow_halts_with_pending_evidence"] = caught and store.connection.execute("SELECT count(*) FROM health WHERE code='queue_overflow'").fetchone()[0] == 1
        collector.asynchronous = False
        collector.close()
        store.close()
    with temporary() as directory:
        store, collector, clock = setup(directory)
        store.connection.close()
        caught = False
        try:
            collector.on_message(None, canonical(quote()))
        except CollectorHalted:
            caught = collector.halt_code == "storage_write_failure" and store.failed
        marker = store.path.with_name(store.path.name + ".failure.jsonl")
        results["storage_error_halts_with_safe_emergency_marker"] = caught and marker.exists() and "storage_write_failure" in marker.read_text()
        store.close()
    with temporary() as directory:
        store, collector, clock = setup(directory, asynchronous=True)
        collector.on_message(None, canonical({"name": "timeSync", "msg": START}))
        for receipt_index in range(120):
            collector.on_message(None, canonical(quote(active=76 if receipt_index % 2 == 0 else 81)))
        collector.close()
        results["actual_background_writer_drains_every_valid_receipt"] = (store.connection.execute("SELECT count(*) FROM observations").fetchone()[0] == 120
                                                                                       and collector.queue.empty() and collector.halt_code is None)
        results["graceful_close_journal_completed_after_queue_drain"] = store.connection.execute("SELECT count(*) FROM sessions WHERE transition='close'").fetchone()[0] == 1
        store.close()
    # Confirm the regression gate rejects the historical multi-size amplification bug.
    original = Adapter.parse
    def mutant(self, raw, receipt):
        result = original(self, raw, receipt)
        if result is not None and result["events"] and result["events"][0]["observation"]["kind"] == "quote":
            result["events"] = result["events"] * 3
        return result
    with patch.object(Adapter, "parse", mutant):
        test = AdapterTests("test_one_top_level_quote_per_actual_all_size_frame")
        outcome = unittest.TextTestRunner(stream=io.StringIO()).run(test)
        results["regression_gate_kills_size_amplification_mutation"] = not outcome.wasSuccessful() and len(outcome.failures) == 1
    score = sum(results.values()) / len(results)
    return {"schema": "fresh_collector_offline_eval_v1", "threshold": THRESHOLD,
            "score": score, "passed": score >= THRESHOLD, "checks": results,
            "details": details, "elapsed_seconds": time.perf_counter() - started,
            "network_calls": 0, "credential_reads": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = evaluate()
    if args.output:
        output = Path(args.output).resolve()
        if not output.is_relative_to(Path("/tmp")):
            raise ValueError("eval evidence must live under /tmp")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(canonical(report) + "\n")
    print(canonical(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
