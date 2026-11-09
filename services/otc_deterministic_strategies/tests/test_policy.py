from dataclasses import replace
import math
import random
import unittest

from ..contracts import InvalidInput, receiver_age_ms
from ..policy import clock_valid, decide, exhaustion_rule, legacy_adx, legacy_rsi, mhi_rule
from .support import ASSET, DECISION_MS, DECISION_NS, candles, inputs


class PolicyTests(unittest.TestCase):
    def call(self, policy='legacy_mhi3_causal', **changes):
        offer, quote, series = inputs()
        return decide(policy, ASSET, changes.get('decision_ns', DECISION_NS),
                      changes.get('offer', offer), changes.get('quote', quote),
                      changes.get('candles', series))

    def test_mhi_existing_thresholds_generate_put_without_calibrated_confidence(self):
        value = self.call()
        self.assertEqual(value.direction, 'put')
        self.assertEqual(value.reason, 'mhi_signal')
        self.assertEqual(value.score, 92.0)
        self.assertFalse(value.capital_permission)
        self.assertEqual(len(value.evidence_sha256), 64)

    def test_downward_shape_generates_call(self):
        series = candles([150.0 - i for i in range(29)])
        series = [replace(item, open=item.close + 0.6, high=item.close + 0.7,
                          low=item.close - 0.1) for item in series]
        value = self.call(candles=series)
        self.assertEqual(value.direction, 'call')

    def test_future_ohlc_and_forming_candles_do_not_change_known_decision(self):
        series = inputs()[2]
        future = replace(series[-1], start_ms=DECISION_MS,
                         received_ns=DECISION_NS + 1, open=math.nan, close=math.inf)
        forming = replace(series[-1], start_ms=DECISION_MS, finalized=False)
        baseline = self.call()
        self.assertEqual(baseline, self.call(candles=series + [future, forming]))

    def test_one_nanosecond_future_offer_or_quote_abstains(self):
        offer, quote, _ = inputs()
        for key, item in [('offer', offer), ('quote', quote)]:
            result = self.call(**{key: replace(item, received_ns=DECISION_NS + 1)})
            self.assertIsNone(result.direction)
            self.assertEqual(result.reason, 'future_offer_or_quote')

    def test_ceil_receipt_age_exact_cutoffs(self):
        self.assertEqual(receiver_age_ms(1000000, 999999), 1)
        offer, quote, _ = inputs()
        for age, accepted in [(5000000000, True), (5000000001, False)]:
            changed = replace(quote, received_ns=DECISION_NS - age,
                              broker_at_receipt_ms=DECISION_MS - age // 1000000)
            self.assertEqual(self.call(quote=changed).should_trade, accepted)
        for age, accepted in [(600000000000, True), (600000000001, False)]:
            changed = replace(offer, received_ns=DECISION_NS - age,
                              broker_at_receipt_ms=DECISION_MS - age // 1000000)
            self.assertEqual(self.call(offer=changed).should_trade, accepted)

    def test_negative_offer_state_overrides_still_fresh_payout(self):
        offer, _, _ = inputs()
        for change in [{'active': False}, {'status': 'unsupported_offer_state'},
                       {'status': 'unknown'}, {'active': 1}]:
            self.assertEqual(self.call(offer=replace(offer, **change)).reason, 'offer_unavailable')

    def test_invalid_scope_or_missing_boundaries_abstain(self):
        offer, quote, _ = inputs()
        for changed in [replace(offer, asset='EURUSD'), replace(offer, product='digital-option')]:
            self.assertEqual(self.call(offer=changed).reason, 'offer_or_quote_scope_mismatch')
        self.assertEqual(self.call(offer=None).reason, 'missing_typed_offer_or_quote')
        self.assertEqual(self.call(quote=replace(quote, clock_status='stale')).reason, 'quote_clock_invalid')

    def test_unknown_and_bad_clock_candles_cannot_complete_prefix(self):
        series = inputs()[2]
        for changed in [replace(series[-1], clock_status='unknown'),
                        replace(series[-1], broker_at_receipt_ms=series[-1].start_ms + 119999),
                        replace(series[-1], finalized=False)]:
            self.assertIsNone(self.call(candles=series[:-1] + [changed]).direction)

    def test_gap_and_stale_closed_prefix_abstain(self):
        series = inputs()[2]
        self.assertEqual(self.call(candles=series[:-5] + series[-4:]).reason,
                         'insufficient_causal_closed_candles')
        shifted = [replace(item, start_ms=item.start_ms + (120000 if i >= 10 else 0),
                           received_ns=item.received_ns + (120000000000 if i >= 10 else 0),
                           broker_at_receipt_ms=item.broker_at_receipt_ms + (120000 if i >= 10 else 0))
                   for i, item in enumerate(series)]
        offer, quote, _ = inputs()
        now_ms = DECISION_MS + 120000
        new_offer = replace(offer, received_ns=now_ms * 1000000, broker_at_receipt_ms=now_ms,
                            expiry_ms=now_ms + 120000, purchase_deadline_ms=now_ms + 90000)
        new_quote = replace(quote, received_ns=now_ms * 1000000, broker_at_receipt_ms=now_ms)
        self.assertEqual(self.call(candles=shifted, decision_ns=now_ms * 1000000,
                                  offer=new_offer, quote=new_quote).reason, 'closed_candle_gap')

    def test_conflicting_same_receipt_and_bad_known_ohlc_raise(self):
        series = inputs()[2]
        conflict = replace(series[-1], close=series[-1].close + 0.01)
        with self.assertRaises(InvalidInput):
            self.call(candles=series + [conflict])
        for changed in [replace(series[-1], open=math.nan), replace(series[-1], high=0.0),
                        replace(series[-1], received_ns=True), replace(series[-1], finalized=1)]:
            with self.assertRaises(InvalidInput):
                self.call(candles=series[:-1] + [changed])

    def test_latest_causal_revision_selected_but_future_revision_ignored(self):
        series = inputs()[2]
        prior = replace(series[-1], received_ns=series[-1].received_ns - 1000000,
                        broker_at_receipt_ms=series[-1].broker_at_receipt_ms,
                        close=series[-1].close - 0.01)
        self.assertEqual(self.call(), self.call(candles=series[:-1] + [prior, series[-1]]))

    def test_nan_bool_and_extreme_numeric_values_cannot_emit_signal(self):
        offer, quote, _ = inputs()
        for value in [math.nan, math.inf, True, '0.85']:
            with self.assertRaises(InvalidInput):
                self.call(offer=replace(offer, payout=value))
        with self.assertRaises(InvalidInput):
            self.call(decision_ns=True)
        with self.assertRaises((InvalidInput, OverflowError)):
            extreme = candles([1e307 if i % 2 else 1e308 for i in range(29)])
            extreme = [replace(item, open=item.close / 9, high=item.close,
                               low=item.close / 10) for item in extreme]
            self.call(candles=extreme)

    def test_purchase_cutoff_and_offered_expiry_not_inferred_from_wall_clock(self):
        offer, _, _ = inputs()
        for changed in [replace(offer, purchase_deadline_ms=DECISION_MS),
                        replace(offer, expiry_ms=DECISION_MS + 60000),
                        replace(offer, expiry_ms=DECISION_MS + 180000),
                        replace(offer, purchase_deadline_ms=offer.expiry_ms)]:
            self.assertIsNone(self.call(offer=changed).direction)

    def test_price_affine_transform_preserves_direction(self):
        series = inputs()[2]
        changed = [replace(item, open=item.open * 1.7 + 10, close=item.close * 1.7 + 10,
                           low=item.low * 1.7 + 10, high=item.high * 1.7 + 10) for item in series]
        self.assertEqual(self.call().direction, self.call(candles=changed).direction)

    def test_exhaustion_calm_rsi_gate_rejects_runaway_path(self):
        value = self.call(policy='legacy_exhaustion_causal')
        self.assertIsNone(value.direction)
        self.assertEqual(value.reason, 'exhaustion_rsi_outside_calm_band')
        self.assertEqual(legacy_rsi([100.0] * 29), 50.0)
        self.assertEqual(legacy_adx(candles([100.0] * 29)), 0.0)
        self.assertIsNone(exhaustion_rule(candles([100.0] * 29))[0])

    def test_expanded_execution_universe_requires_explicit_validated_named_otc_assets(self):
        offer, quote, series = inputs()
        asset = 'USDJPY-OTC'
        offer, quote = replace(offer, asset=asset), replace(quote, asset=asset)
        series = [replace(item, asset=asset) for item in series]
        with self.assertRaises(InvalidInput):
            decide('legacy_mhi3_causal', asset, DECISION_NS, offer, quote, series)
        result = decide('legacy_mhi3_causal', asset, DECISION_NS, offer, quote, series,
                        allowed_assets=(ASSET, asset))
        self.assertEqual(result.direction, 'put')
        for scope in [(asset, asset), ('USDJPY',), ['USDJPY-OTC'], ()]:
            with self.assertRaises(InvalidInput):
                decide('legacy_mhi3_causal', asset, DECISION_NS, offer, quote, series,
                       allowed_assets=scope)

    def test_exhaustion_known_extreme_calm_path_generates_put(self):
        generator = random.Random(20261109)
        closes = [100.0 + generator.gauss(0, 1) for _ in range(28)]
        closes += [100.0 + generator.choice((-1, 1)) * generator.uniform(2, 4)]
        series = [replace(item, open=item.close + 0.1, high=item.close + 0.4,
                          low=item.close - 0.4) for item in candles(closes)]
        self.assertEqual(self.call(policy='legacy_exhaustion_causal', candles=series).direction, 'put')

    def test_holding_bounds_preserve_exact_nanoseconds_for_both_fixed_policies(self):
        generator = random.Random(20261109)
        closes = [100.0 + generator.gauss(0, 1) for _ in range(28)]
        closes += [100.0 + generator.choice((-1, 1)) * generator.uniform(2, 4)]
        exhaustion_series = [replace(item, open=item.close + 0.1, high=item.close + 0.4,
                                      low=item.close - 0.4) for item in candles(closes)]
        initial_offer, quote, mhi_series = inputs()
        quote = replace(quote, received_ns=DECISION_NS - 1000000,
                        broker_at_receipt_ms=DECISION_MS - 1)
        for policy, series in [('legacy_mhi3_causal', mhi_series),
                               ('legacy_exhaustion_causal', exhaustion_series)]:
            for requested_ms, delta_ns, allowed in [(90000, 1, False), (90000, 0, True),
                                                    (150000, 0, True), (150000, -1, False)]:
                with self.subTest(policy=policy, requested_ms=requested_ms, delta_ns=delta_ns):
                    offer = replace(initial_offer, received_ns=DECISION_NS - 1000000,
                                    broker_at_receipt_ms=DECISION_MS - 1,
                                    expiry_ms=DECISION_MS + requested_ms,
                                    purchase_deadline_ms=DECISION_MS + requested_ms - 30000)
                    result = self.call(policy=policy, decision_ns=DECISION_NS + delta_ns,
                                       offer=offer, quote=quote, candles=series)
                    self.assertEqual(result.should_trade, allowed)
                    if not allowed:
                        self.assertEqual(result.reason, 'offer_not_two_minute_request')

    def test_closed_candle_staleness_uses_exact_derived_broker_nanoseconds(self):
        offer, quote, series = inputs()
        future_ms = DECISION_MS + 120000
        offer = replace(offer, received_ns=future_ms * 1000000,
                        broker_at_receipt_ms=future_ms, expiry_ms=future_ms + 120000,
                        purchase_deadline_ms=future_ms + 90000)
        quote = replace(quote, received_ns=future_ms * 1000000,
                        broker_at_receipt_ms=future_ms)
        at_limit = self.call(decision_ns=future_ms * 1000000, offer=offer, quote=quote, candles=series)
        self.assertTrue(at_limit.should_trade)
        beyond = self.call(decision_ns=future_ms * 1000000 + 1, offer=offer, quote=quote, candles=series)
        self.assertEqual(beyond.reason, 'stale_closed_candle')

    def test_purchase_deadline_one_nanosecond_before_and_at_cutoff(self):
        offer, quote, series = inputs()
        offer = replace(offer, received_ns=DECISION_NS - 1000000,
                        broker_at_receipt_ms=DECISION_MS - 1,
                        purchase_deadline_ms=DECISION_MS + 1)
        quote = replace(quote, received_ns=DECISION_NS - 1000000,
                        broker_at_receipt_ms=DECISION_MS - 1)
        before = self.call(decision_ns=DECISION_NS + 999999, offer=offer, quote=quote, candles=series)
        at_cutoff = self.call(decision_ns=DECISION_NS + 1000000, offer=offer, quote=quote, candles=series)
        self.assertTrue(before.should_trade)
        self.assertEqual(at_cutoff.reason, 'offer_purchase_cutoff_reached')

    def test_exact_signed_broker_clock_offsets_preserve_one_nanosecond_limit(self):
        broker_ms = DECISION_MS
        for offset_ns, expected in [(15000000000, True), (15000000001, False),
                                    (-15000000000, True), (-15000000001, False)]:
            with self.subTest(offset_ns=offset_ns):
                received_ns = broker_ms * 1000000 - offset_ns
                self.assertEqual(clock_valid(received_ns, broker_ms, 'ok'), expected)
        offer, quote, series = inputs()
        excessive_receipt = DECISION_NS + 15000000001
        invalid_quote = replace(quote, received_ns=excessive_receipt,
                                broker_at_receipt_ms=DECISION_MS)
        self.assertEqual(self.call(decision_ns=excessive_receipt, quote=invalid_quote).reason,
                         'quote_clock_invalid')
        invalid_offer = replace(offer, received_ns=excessive_receipt,
                                broker_at_receipt_ms=DECISION_MS)
        valid_quote = replace(quote, received_ns=excessive_receipt,
                              broker_at_receipt_ms=(excessive_receipt // 1000000))
        self.assertEqual(self.call(decision_ns=excessive_receipt, offer=invalid_offer,
                                  quote=valid_quote).reason, 'offer_clock_invalid')


if __name__ == '__main__':
    unittest.main()
