"""Focused regression for broker timestamps finer than integer milliseconds."""
from decimal import Decimal, localcontext
import io
import json
import unittest
from unittest.mock import patch
from services.otc_collector.adapter import Adapter, InvalidFrame, Receipt, epoch, epoch_details

BASE_MS = 1_893_456_000_000
CASES = (
    ("1893456000.123456", "seconds", "1893456000123.456", "0.456", "0.001"),
    ("1893456000123.456", "milliseconds", "1893456000123.456", "0.456", "0.001"),
    ("1893456000123456", "microseconds", "1893456000123.456", "0.456", "0.001"),
    ("1893456000123456789", "nanoseconds", "1893456000123.456789", "0.456789", "0.000001"),
    ("1893456000123456.789", "microseconds", "1893456000123.456789", "0.456789", "0.000001"),
    ("1893456000123456789.125", "nanoseconds", "1893456000123.456789125", "0.456789125", "1E-9"),
)


class FractionalStampTests(unittest.TestCase):
    def test_exact_unit_mapping_and_floor_with_original_precision(self):
        for raw, unit, exact, fraction, resolution in CASES:
            with self.subTest(raw=raw):
                stamp, metadata = epoch_details(Decimal(raw))
                self.assertEqual(stamp, BASE_MS + 123)
                self.assertEqual(metadata["broker_stamp_text"], raw)
                self.assertEqual(metadata["broker_stamp_unit"], unit)
                self.assertEqual(metadata["source_stamp_unit"], {"seconds": "s", "milliseconds": "ms", "microseconds": "us", "nanoseconds": "ns"}[unit])
                self.assertEqual(metadata["broker_stamp_ms_exact"], exact)
                self.assertEqual(metadata["broker_stamp_fractional_ms"], fraction)
                self.assertEqual(metadata["broker_stamp_resolution_ms"], resolution)
                self.assertEqual(metadata["broker_stamp_ms_rounding"], "floor")
    def test_high_rate_ns_receipts_preserved_even_with_equal_metadata_ms(self):
        adapter = Adapter()
        receipt = Receipt("new-source-version", 1, BASE_MS + 124, 1000)
        adapter.parse('{"name":"timeSync","msg":1893456000124}', receipt)
        events = []
        for sequence, raw_stamp in enumerate(("1893456000123456001", "1893456000123456999"), 2):
            raw = '{"name":"candles-generated","msg":{"active_id":76,"at":' + raw_stamp + ',"bid":1.1,"ask":1.2}}'
            received = Receipt(receipt.session_id, sequence, receipt.received_at_ms, sequence * 1000)
            events.append(adapter.parse(raw, received)["events"][0])
        self.assertNotEqual(events[0]["observation"]["event_id"], events[1]["observation"]["event_id"])
        self.assertEqual([event["lineage"]["source_event_ms"] for event in events], [BASE_MS + 123] * 2)
        self.assertEqual([event["lineage"]["broker_stamp_text"] for event in events], ["1893456000123456001", "1893456000123456999"])
        self.assertEqual([event["observation"]["available_ms"] for event in events], [BASE_MS + 124] * 2)
        self.assertEqual([event["observation"]["event_ms"] for event in events], [BASE_MS + 124] * 2)
        self.assertEqual([event["lineage"]["clock_status"] for event in events], ["ok"] * 2)
    def test_wire_lexeme_including_exponent_and_trailing_zeros_is_preserved(self):
        adapter = Adapter()
        receipt = Receipt("v2", 1, BASE_MS + 124, 1000)
        for raw_stamp in ("1893456000123.456000", "1.893456000123456e18"):
            raw = '{"name":"candles-generated","msg":{"active_id":76,"at":' + raw_stamp + ',"bid":1.1,"ask":1.2}}'
            meta = adapter.parse(raw, receipt)["events"][0]["lineage"]
            self.assertEqual(meta["broker_stamp_text"], raw_stamp)
    def test_mapping_ignores_ambient_decimal_precision(self):
        with localcontext() as context:
            context.prec = 3
            stamp, metadata = epoch_details(Decimal("1893456000123456789.125"))
        self.assertEqual(stamp, BASE_MS + 123)
        self.assertEqual(metadata["broker_stamp_ms_exact"], "1893456000123.456789125")
    def test_false_epochs_still_rejected(self):
        invalid = (True, False, None, "1893456000123.456", 0, -1, Decimal("NaN"), Decimal("Infinity"),
                   Decimal("1262303999999.999"), Decimal("4102444800000.001"), Decimal("9999999999999999999999999999999999999"))
        for value in invalid:
            with self.subTest(value=str(value)), self.assertRaises(InvalidFrame):
                epoch(value)
    def test_floor_never_rounds_a_source_stamp_into_future_ms(self):
        stamp, metadata = epoch_details(Decimal("1893456000123.999999"))
        self.assertEqual(stamp, BASE_MS + 123)
        self.assertEqual(metadata["broker_stamp_fractional_ms"], "0.999999")
    def test_fractional_time_sync_retains_raw_semantics(self):
        receipt = Receipt("v2", 1, BASE_MS + 124, 1000)
        result = Adapter().parse('{"name":"timeSync","msg":1893456000.124999}', receipt)
        self.assertEqual(result["health"]["broker_source_ms"], BASE_MS + 124)
        self.assertEqual(result["health"]["broker_stamp_text"], "1893456000.124999")
        self.assertEqual(result["health"]["broker_stamp_fractional_ms"], "0.999")
    def test_actual_broker_ns_samples_and_exact_receiver_diagnostic(self):
        raw_stamps = ("1794045176612157505", "1794045176667081366", "1794045176748331938", "1794045177000000000")
        received_ns = 1794045176714703156
        for raw_stamp in raw_stamps:
            with self.subTest(raw_stamp=raw_stamp):
                receipt = Receipt("v2", 1, received_ns // 1_000_000, 1000, received_ns)
                raw = '{"name":"candles-generated","msg":{"active_id":76,"at":' + raw_stamp + ',"bid":1.1,"ask":1.2}}'
                event = Adapter().parse(raw, receipt)["events"][0]
                self.assertEqual(event["lineage"]["source_event_ms"], int(raw_stamp) // 1_000_000)
                self.assertEqual(event["lineage"]["source_stamp_unit"], "ns")
                self.assertEqual(event["lineage"]["broker_stamp_text"], raw_stamp)
                self.assertEqual(event["lineage"]["broker_stamp_ns_exact"], raw_stamp)
                self.assertEqual(event["lineage"]["received_at_ns"], received_ns)
                self.assertEqual(event["lineage"]["raw_source_receiver_delta_ns"], str(received_ns - int(raw_stamp)))
                self.assertEqual(event["observation"]["available_ms"], received_ns // 1_000_000)
                self.assertEqual(event["observation"]["event_ms"], received_ns // 1_000_000)
    def test_callback_uses_one_receiver_ns_sample_before_parse(self):
        from services.otc_collector.collector import Collector
        received_ns = 1794045176714703156
        records = []
        class Store:
            registration = {"start_ms": received_ns // 1_000_000 - 1, "end_ms": received_ns // 1_000_000 + 1}
            def open_session(self, **kwargs):
                return "v2"
            def append(self, envelope):
                records.append(envelope)
        wall_ns = unittest.mock.Mock(return_value=received_ns)
        collector = Collector(Store(), wall_clock=lambda: received_ns // 1_000_000, wall_clock_ns=wall_ns, monotonic_clock=lambda: 1000)
        collector.on_message(None, '{"name":"candles-generated","msg":{"active_id":76,"at":1794045176612157505,"bid":1.1,"ask":1.2}}')
        wall_ns.assert_called_once_with()
        self.assertEqual(records[0]["received_at_ns"], received_ns)
        self.assertEqual(records[0]["received_at_ms"], received_ns // 1_000_000)


def focused_eval():
    """The old integer-only millisecond rule must fail the exact mapping regression."""
    from services.otc_collector import adapter as module
    original = module.epoch_details
    def old_rule(value):
        stamp, meta = original(value)
        if Decimal(meta["broker_stamp_fractional_ms"]) != 0:
            raise InvalidFrame("invalid_source_stamp")
        return stamp, meta
    result = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.defaultTestLoader.loadTestsFromTestCase(FractionalStampTests))
    with patch.object(module, "epoch_details", old_rule):
        mutant = unittest.TextTestRunner(stream=io.StringIO()).run(FractionalStampTests("test_high_rate_ns_receipts_preserved_even_with_equal_metadata_ms"))
    return {"tests": result.testsRun, "errors": len(result.errors), "failures": len(result.failures),
            "pass_threshold": 1.0, "passed": result.wasSuccessful() and not mutant.wasSuccessful(),
            "old_integer_only_rule_rejected": not mutant.wasSuccessful(), "network_calls": 0, "credential_reads": 0}


if __name__ == "__main__":
    report = focused_eval()
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["passed"] else 1)
