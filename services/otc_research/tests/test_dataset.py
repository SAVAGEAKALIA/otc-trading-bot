"""Gate tests: python -m unittest -v test_dataset.py."""
from copy import deepcopy
from decimal import Decimal, localcontext, ROUND_UP
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

from services.otc_research.dataset import ContractError, build_rows
from services.otc_research.export import HISTORICAL_END_MS, load_boundary, opportunities_for
from services.otc_research.tests.dataset_fixtures import boundary_manifest, config, observation, observations, opportunity, payload


def build(data=None):
    return build_rows(**(data or payload()))


class DatasetTests(unittest.TestCase):
    def test_receiver_terminal_cannot_precede_modeled_entry(self):
        data = payload()
        data["config"].update(terminal_policy="last_received_before")
        data["config"]["max_age_ms"]["quote"] = 3000
        for record in data["observations"] + data["opportunities"]:
            record["clock_id"] = "receiver_utc"
        data["opportunities"][0]["expiry_basis"] = "hypothetical"
        data["observations"] = [record for record in data["observations"] if record["event_id"] not in {"q-entry", "q-terminal"}]
        data["observations"].append(observation("entry-secondary", "quote", 1010, "101", source="secondary", clock_id="receiver_utc"))
        row = build(data)["rows"][0]
        self.assertEqual(row["status"], "unresolved")
        self.assertIn("terminal_quote_precedes_modeled_entry", row["reason_codes"])

    def test_batch_entry_newest_tick_and_invalid_fraction_bounds(self):
        data = payload()
        entry = next(o for o in data["observations"] if o["event_id"] == "q-entry")
        entry["available_ms"] = 1020
        data["observations"].append(observation("new-batch", "quote", 1018, "102", available_ms=1020))
        row = build(data)["rows"][0]
        self.assertEqual((row["modeled_strike"], row["label"], row["unit_pnl"]), ("102", "down", "-1"))
        for kind, value in [("mood", "1.01"), ("mood", "-.01"), ("payout", "2.01"), ("payout", "-.01")]:
            corrupted = payload()
            corrupted["observations"].append(observation("bad-fraction", kind, 3000, value))
            with self.subTest(kind=kind,value=value), self.assertRaises(ContractError):
                build(corrupted)

    def test_positive_and_negative_returns_for_each_direction(self):
        for terminal, direction, label, pnl in [("101", "call", "up", ".8"), ("101", "put", "up", "-1"),
                                                 ("99", "call", "down", "-1"), ("99", "put", "down", ".8")]:
            with self.subTest(terminal=terminal, direction=direction):
                data = payload()
                data["observations"][-1]["value"] = terminal
                data["opportunities"][0]["direction"] = direction
                row = build(data)["rows"][0]
                self.assertEqual(row["status"], "resolved")
                self.assertTrue(row["training_eligible"])
                self.assertEqual(row["label"], label)
                self.assertEqual(Decimal(row["unit_pnl"]), Decimal(pnl))
                self.assertFalse(row["executable_edge_eligible"])
                self.assertEqual(row["modeled_strike"], "100")

    def test_features_and_full_lineage(self):
        row = build()["rows"][0]
        self.assertEqual(row["features"]["last_quote"], "100")
        self.assertEqual(Decimal(row["features"]["market_mood"]), Decimal(".5"))
        self.assertEqual(row["features"]["market_mood_count"], 2)
        self.assertEqual(row["features"]["quote_age_ms"], 50)
        self.assertEqual(row["features"]["mood_age_ms"], 60)
        self.assertEqual(row["features"]["payout_age_ms"], 100)
        self.assertEqual(row["lineage"], {"decision_quote": "q-decision", "payout": "p-decision", "lookback_quote": "q-lookback",
                                          "own_mood": "m-own", "market_mood": ["m-own", "m-other"],
                                          "modeled_strike": "q-entry", "terminal_quote": "q-terminal"})

    def test_tie_is_retained_and_refunded_or_explicitly_lost(self):
        data = payload()
        data["observations"][-1]["value"] = "100"
        for rule, pnl in [("full_refund", "0"), ("loss", "-1")]:
            data["config"]["tie_rule"] = rule
            result = build(data)
            row = result["rows"][0]
            self.assertEqual(row["label"], "tie")
            self.assertEqual(row["unit_pnl"], pnl)
            self.assertTrue(row["training_eligible"])
            self.assertEqual(result["counts"]["ties"], 1)
        del data["config"]["tie_rule"]
        with self.assertRaises(ContractError):
            build(data)

    def test_direction_can_be_omitted_without_inventing_policy(self):
        data = payload()
        del data["opportunities"][0]["direction"]
        row = build(data)["rows"][0]
        self.assertEqual(row["label"], "up")
        self.assertIsNone(row["unit_pnl"])

    def test_future_payout_cannot_fill_missing_payout_or_apply_floor(self):
        data = payload()
        data["observations"] = [o for o in data["observations"] if o["kind"] != "payout"]
        data["observations"].append(observation("future-payout", "payout", 1500, "0.99"))
        row = build(data)["rows"][0]
        self.assertEqual(row["status"], "ineligible")
        self.assertIsNone(row["features"])
        self.assertIn("missing_positive_decision_payout", row["reason_codes"])
        self.assertIsNone(row["unit_pnl"])

    def test_nonpositive_current_payout_never_resurrects_old_offer(self):
        data = payload()
        data["observations"].append(observation("zero-payout", "payout", 990, "0"))
        self.assertEqual(build(data)["rows"][0]["status"], "ineligible")

    def test_quote_and_payout_freshness_use_event_time_not_late_arrival(self):
        for kind in ("quote", "payout"):
            data = payload()
            data["observations"] = [o for o in data["observations"] if o["kind"] != kind]
            data["observations"].append(observation("old-arrived-now", kind, 100, "100" if kind == "quote" else ".8", available_ms=999))
            row = build(data)["rows"][0]
            self.assertEqual(row["status"], "ineligible")

    def test_recent_source_event_with_future_receipt_is_invisible(self):
        data = payload()
        data["observations"] = [o for o in data["observations"] if o["kind"] != "payout"]
        data["observations"].append(observation("late-payout", "payout", 990, ".8", available_ms=1001))
        self.assertEqual(build(data)["rows"][0]["status"], "ineligible")

    def test_missing_receipts_and_bucket_only_cannot_create_training_context(self):
        for updates in ({"available_ms": None}, {"quality": "bucket_only"}):
            data = payload()
            payout_record = next(o for o in data["observations"] if o["kind"] == "payout")
            payout_record.update(updates)
            self.assertEqual(build(data)["rows"][0]["status"], "ineligible")

    def test_mood_optional_and_lookback_never_backfilled_from_future(self):
        data = payload()
        data["observations"] = [o for o in data["observations"] if o["kind"] != "mood" and o["event_id"] != "q-lookback"]
        row = build(data)["rows"][0]
        self.assertTrue(row["training_eligible"])
        for field in ("own_mood", "market_mood", "return_lookback", "mood_age_ms"):
            self.assertIsNone(row["features"][field])
        self.assertTrue(row["features"]["own_mood_missing"])
        self.assertTrue(row["features"]["return_lookback_missing"])

    def test_other_asset_future_quote_and_doji_do_not_change_market_mood(self):
        data = payload()
        baseline = build(data)["rows"][0]["features"]
        for asset in ("EURUSD-OTC", "GBPUSD-OTC", "NEVER-SEEN"):
            data["observations"].extend([observation(f"{asset}-future-1", "quote", 2010, "100", asset=asset),
                                          observation(f"{asset}-future-2", "quote", 2020, "100", asset=asset),
                                          observation(f"{asset}-future-mood", "mood", 2040, ".99", asset=asset)])
        self.assertEqual(build(data)["rows"][0]["features"], baseline)

    def test_product_broker_clock_scopes_and_source_priority(self):
        data = payload()
        baseline = build(data)["rows"][0]["features"]
        additions = [{"product": "digital"}, {"broker": "elsewhere"}, {"clock_id": "different"}, {"source": "unregistered"}]
        for number, update in enumerate(additions):
            data["observations"].append(observation(f"wrong-{number}", "mood", 990, ".99", **update))
        data["observations"].append(observation("secondary-mood", "mood", 990, ".99", source="secondary"))
        self.assertEqual(build(data)["rows"][0]["features"], baseline)

    def test_stale_primary_falls_through_to_fresh_secondary(self):
        data = payload()
        data["observations"] = [o for o in data["observations"] if o["kind"] != "payout"]
        data["observations"].extend([observation("stale", "payout", 100, ".9", available_ms=998),
                                      observation("fresh-secondary", "payout", 990, ".7", source="secondary")])
        row = build(data)["rows"][0]
        self.assertTrue(row["training_eligible"])
        self.assertEqual(Decimal(row["features"]["payout"]), Decimal(".7"))
        self.assertEqual(row["lineage"]["payout"], "fresh-secondary")

    def test_old_arrival_does_not_mask_previously_arrived_fresh_event(self):
        data = payload()
        data["observations"].append(observation("old-late", "quote", 100, "3", available_ms=999))
        self.assertEqual(build(data)["rows"][0]["lineage"]["decision_quote"], "q-decision")

    def test_missing_settlement_is_retained_after_selection(self):
        data = payload()
        data["observations"] = [o for o in data["observations"] if o["event_id"] != "q-terminal"]
        result = build(data)
        self.assertEqual(result["counts"], {"total": 1, "before_label_eligible": 1, "resolved": 0, "unresolved": 1, "ineligible": 0, "ties": 0})
        row = result["rows"][0]
        self.assertIsNotNone(row["features"])
        self.assertEqual(row["modeled_strike"], "100")
        self.assertIsNone(row["label"])
        self.assertFalse(row["training_eligible"])

    def test_exact_expiry_only_without_interpolation(self):
        data = payload()
        data["observations"] = [o for o in data["observations"] if o["event_id"] != "q-terminal"]
        data["observations"].extend([observation("near-before", "quote", 1999, "90"), observation("near-after", "quote", 2001, "110")])
        self.assertEqual(build(data)["rows"][0]["status"], "unresolved")
        data["observations"].append(observation("exact-late", "quote", 2000, "101", available_ms=2050))
        self.assertEqual(build(data)["rows"][0]["status"], "resolved")
        data["observations"][-1]["available_ms"] = 2051
        self.assertEqual(build(data)["rows"][0]["status"], "unresolved")

    def test_entry_deadlines_and_source_event_time(self):
        for event_ms, arrival, status in [(1010, 1110, "resolved"), (1010, 1111, "unresolved"), (1009, 1010, "unresolved")]:
            data = payload()
            entry = next(o for o in data["observations"] if o["event_id"] == "q-entry")
            entry.update(event_ms=event_ms, available_ms=arrival)
            with self.subTest(event_ms=event_ms, arrival=arrival):
                self.assertEqual(build(data)["rows"][0]["status"], status)
        data = payload()
        data["opportunities"][0]["latest_entry_ms"] = 1010
        self.assertEqual(build(data)["rows"][0]["status"], "resolved")
        data["opportunities"][0]["latest_entry_ms"] = 1009
        self.assertEqual(build(data)["rows"][0]["status"], "ineligible")
        data = payload()
        data["opportunities"][0].update(acceptance_delay_ms=1000, latest_entry_ms=1999)
        self.assertEqual(build(data)["rows"][0]["status"], "ineligible")
        for cutoff in (999, 2000, 2001):
            invalid = payload()
            invalid["opportunities"][0]["latest_entry_ms"] = cutoff
            with self.subTest(cutoff=cutoff), self.assertRaises(ContractError):
                build(invalid)

    def test_first_entry_receipt_then_priority_for_equal_receipts(self):
        data = payload()
        entry = next(o for o in data["observations"] if o["event_id"] == "q-entry")
        entry["available_ms"] = 1020
        data["observations"].append(observation("earlier-secondary", "quote", 1010, "99", source="secondary"))
        self.assertEqual(build(data)["rows"][0]["lineage"]["modeled_strike"], "earlier-secondary")
        data["observations"][-1]["available_ms"] = 1020
        self.assertEqual(build(data)["rows"][0]["lineage"]["modeled_strike"], "q-entry")

    def test_terminal_priority_does_not_average_sources(self):
        data = payload()
        data["observations"].append(observation("other-terminal", "quote", 2000, "90", source="secondary"))
        self.assertEqual(build(data)["rows"][0]["terminal_quote"], "101")

    def test_future_edits_preserve_features_and_before_label_selection(self):
        original = payload()
        before = build(original)
        altered = deepcopy(original)
        for record in altered["observations"]:
            if record["available_ms"] > 1000:
                record["value"] = "999" if record["kind"] == "quote" else ".99"
        altered["observations"].extend([observation("future-mood", "mood", 1001, ".99", asset="FUTURE"),
                                         observation("future-payout", "payout", 1001, ".99")])
        after = build(altered)
        self.assertEqual(before["rows"][0]["features"], after["rows"][0]["features"])
        self.assertEqual(before["counts"]["before_label_eligible"], after["counts"]["before_label_eligible"])

    def test_duplicates_and_source_time_conflicts(self):
        data = payload()
        data["observations"].append(deepcopy(data["observations"][0]))
        self.assertEqual(build(data)["observation_counts"]["duplicate"], 1)
        data["observations"][-1]["value"] = "1000"
        with self.assertRaises(ContractError):
            build(data)
        data["observations"][-1]["event_id"] = "changed-identity-same-time"
        with self.assertRaises(ContractError):
            build(data)
        data = payload()
        data["opportunities"].append(deepcopy(data["opportunities"][0]))
        with self.assertRaises(ContractError):
            build(data)

    def test_fail_closed_nonfinite_malformed_and_unknown_values(self):
        corruptions = [lambda p: p["observations"][0].update(value="NaN"),
                       lambda p: p["observations"][0].update(value="Infinity"),
                       lambda p: p["observations"][0].update(value=1.0),
                       lambda p: p["observations"][0].update(value="0"),
                       lambda p: p["observations"][0].update(available_ms=True),
                       lambda p: p["observations"][0].update(available_ms=799),
                       lambda p: p["observations"][0].update(clock_id=None),
                       lambda p: p["observations"][0].update(clock_id=""),
                       lambda p: p["observations"][0].update(kind="candle"),
                       lambda p: p["observations"][0].update(quality="assumed"),
                       lambda p: p["opportunities"][0].update(evidence_class="accepted_contract"),
                       lambda p: p["opportunities"][0].update(expiry_ms=1000),
                       lambda p: p["opportunities"][0].update(acceptance_delay_ms=-1),
                       lambda p: p["config"].update(lookback_ms=False),
                       lambda p: p["config"].update(unknown_option=1)]
        for corrupt in corruptions:
            with self.subTest(corrupt=corrupt):
                data = payload()
                corrupt(data)
                with self.assertRaises(ContractError):
                    build(data)

    def test_input_order_independent_and_inputs_immutable(self):
        data = payload()
        data["opportunities"].extend([opportunity(opportunity_id="op-0"), opportunity(opportunity_id="earlier", decision_ms=990)])
        original = deepcopy(data)
        expected = build(data)
        self.assertEqual(data, original)
        random.Random(239).shuffle(data["observations"])
        random.Random(739).shuffle(data["opportunities"])
        self.assertEqual(build(data), expected)
        self.assertEqual([r["opportunity_id"] for r in expected["rows"]], ["earlier", "op-0", "op-1"])

    def test_decimal_result_independent_of_caller_context(self):
        expected = build()
        with localcontext() as context:
            context.prec = 2
            context.rounding = ROUND_UP
            self.assertEqual(build(), expected)

    def test_hypothetical_expiry_stays_explicit_research_proxy(self):
        data = payload()
        data["opportunities"][0]["expiry_basis"] = "hypothetical"
        result = build(data)
        self.assertTrue(result["research_only"])
        self.assertFalse(result["accepted_contract_cash"])
        self.assertEqual(result["rows"][0]["expiry_basis"], "hypothetical")
        self.assertFalse(result["rows"][0]["executable_edge_eligible"])

    def test_explicit_receiver_terminal_policy_uses_only_pre_expiry_receipts(self):
        data = payload()
        data["config"]["terminal_policy"] = "last_received_before"
        for item in data["observations"] + data["opportunities"]:
            item["clock_id"] = "receiver_utc"
        data["opportunities"][0]["expiry_basis"] = "hypothetical"
        data["observations"][-1].update(event_ms=1999, available_ms=1999)
        first = build(data)
        self.assertEqual(first["rows"][0]["label"], "up")
        self.assertEqual(first["terminal_policy"], "last_received_before")
        data["observations"].append(observation("post-expiry", "quote", 2001, "50", clock_id="receiver_utc"))
        self.assertEqual(build(data)["rows"][0], first["rows"][0])
        data["observations"] = [o for o in data["observations"] if o["event_id"] != "q-terminal"]
        self.assertEqual(build(data)["rows"][0]["status"], "unresolved")

    def test_receiver_terminal_policy_rejects_source_clock_or_broker_offer(self):
        data = payload()
        data["config"]["terminal_policy"] = "last_received_before"
        with self.assertRaises(ContractError):
            build(data)
        for item in data["observations"] + data["opportunities"]:
            item["clock_id"] = "receiver_utc"
        data["opportunities"][0]["expiry_basis"] = "hypothetical"
        data["observations"][0]["available_ms"] += 1
        with self.assertRaises(ContractError):
            build(data)

    def test_cli_serializes_reproducibly_and_rejects_nonfinite_json(self):
        from contextlib import redirect_stdout, redirect_stderr
        import io
        from unittest.mock import patch
        from services.otc_research.dataset import main
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "input.json"
            source.write_text(json.dumps(payload()))
            outputs = []
            for _ in range(2):
                stdout = io.StringIO()
                with patch.object(sys, "argv", ["dataset", str(source)]), redirect_stdout(stdout):
                    main()
                outputs.append(stdout.getvalue())
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(json.loads(outputs[0]), build())
            source.write_text('{"observations": NaN, "opportunities": [], "config": {}}')
            stdout = io.StringIO()
            with patch.object(sys, "argv", ["dataset", str(source)]), redirect_stdout(stdout), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                main()
            self.assertEqual(raised.exception.code, 2)
            self.assertEqual(stdout.getvalue(), "")


class ExportBoundaryTests(unittest.TestCase):
    def test_valid_bounds_preserve_fixed_grid_and_empty_sources(self):
        manifest = boundary_manifest()
        expected = [('EURUSD-OTC', 120000), ('GBPUSD-OTC', 120000),
                    ('EURUSD-OTC', 240000), ('GBPUSD-OTC', 240000)]
        rows = opportunities_for(manifest)
        self.assertEqual([(row['asset'], row['decision_ms']) for row in rows], expected)
        self.assertTrue(all(row['expiry_ms'] == row['decision_ms'] + 120000 and
                            row['latest_entry_ms'] == row['decision_ms'] + 2000 and
                            row['clock_id'] == 'receiver_utc' and row['direction'] is None for row in rows))
        for kind in ('mood', 'payout', 'quote'):
            manifest['receipt_bounds'][kind] = {'first_receipt_ms': None, 'last_receipt_ms': None}
            manifest['inventory'][kind + '_samples']['rows_in_scope'] = 0
            rows = opportunities_for(manifest)
            self.assertEqual([(row['asset'], row['decision_ms']) for row in rows], expected if kind != 'quote' else [])

    def test_noninteger_receipt_endpoints_rejected(self):
        for kind in ('quote', 'mood', 'payout'):
            for field in ('first_receipt_ms', 'last_receipt_ms'):
                for invalid in (True, False, 120000.0, '120000', None, [], {}):
                    manifest = boundary_manifest()
                    manifest['receipt_bounds'][kind][field] = invalid
                    with self.subTest(kind=kind, field=field, invalid=invalid), self.assertRaises(ValueError):
                        opportunities_for(manifest)

    def test_per_source_reverse_and_scope_bounds_rejected_before_allocation(self):
        from unittest.mock import patch
        for kind in ('quote', 'mood', 'payout'):
            for first, last in ((360000, 0), (-1, 250000), (100001, HISTORICAL_END_MS),
                                (HISTORICAL_END_MS, HISTORICAL_END_MS + 1)):
                manifest = boundary_manifest()
                manifest['receipt_bounds'][kind] = {'first_receipt_ms': first, 'last_receipt_ms': last}
                with self.subTest(kind=kind, first=first, last=last), patch('services.otc_research.export.Opportunity', side_effect=AssertionError('Allocated malformed grid')), self.assertRaises(ValueError):
                    opportunities_for(manifest)

    def test_bound_objects_and_fields_must_be_exact(self):
        for missing in ('quote', 'mood', 'payout'):
            manifest = boundary_manifest(); del manifest['receipt_bounds'][missing]
            with self.subTest(missing=missing), self.assertRaises(ValueError): opportunities_for(manifest)
        for invalid in (None, [], {}, {'first_receipt_ms': 1},
                        {'first_receipt_ms': 1, 'last_receipt_ms': 250000, 'extra': 1}):
            manifest = boundary_manifest(); manifest['receipt_bounds']['mood'] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError): opportunities_for(manifest)
        manifest = boundary_manifest(); manifest['receipt_bounds']['unregistered'] = {'first_receipt_ms': 1, 'last_receipt_ms': 250000}
        with self.assertRaises(ValueError): opportunities_for(manifest)

    def test_inventory_and_registered_scope_are_required(self):
        corruptions = [lambda m: m.pop('receipt_bounds'), lambda m: m.pop('inventory'),
                       lambda m: m.update(clock='source_utc'), lambda m: m.update(product='binary'),
                       lambda m: m.update(assets=['EURUSD-OTC']), lambda m: m.update(promotable=0),
                       lambda m: m.update(source_stable=1), lambda m: m.update(status='RUNNING'),
                       lambda m: m['inventory'].pop('mood_samples'),
                       lambda m: m['inventory'].update(extra={'rows_in_scope': 1})]
        for invalid in (True, -1, 2.0, '2', None):
            corruptions.append(lambda m, value=invalid: m['inventory']['mood_samples'].update(rows_in_scope=value))
        corruptions.extend([lambda m: m['inventory']['mood_samples'].update(rows_in_scope=0),
                            lambda m: m['receipt_bounds']['mood'].update(first_receipt_ms=None, last_receipt_ms=None)])
        for number, corrupt in enumerate(corruptions):
            manifest = boundary_manifest(); corrupt(manifest)
            with self.subTest(case=number), self.assertRaises(ValueError): opportunities_for(manifest)

    def test_malformed_boundary_rejected_before_hashing_payload(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); manifest = boundary_manifest()
            manifest['receipt_bounds']['quote']['first_receipt_ms'] = True
            (root / 'manifest.json').write_text(json.dumps(manifest))
            with patch('services.otc_research.export.sha256', side_effect=AssertionError('Read payload before metadata validation')), self.assertRaises(ValueError):
                load_boundary(root)


if __name__ == "__main__":
    unittest.main()
