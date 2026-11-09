"""Every causal finalized identity must agree, independent of input order."""
from dataclasses import replace
from itertools import permutations
import math
import unittest

from ..contracts import ASSETS, POLICIES, Candle, InvalidInput, Offer, Quote
from ..policy import decide

MS_NS = 1000000
BAR_MS = 120000


def positive_inputs(policy, offset_bars=0):
    start_ms = offset_bars * BAR_MS
    decision_ms = start_ms + 29 * BAR_MS
    decision_ns = decision_ms * MS_NS
    if policy == POLICIES[0]:
        closes = [100.0 + index for index in range(29)]
        prices = [(close - 0.6, close + 0.1, close - 0.7, close) for close in closes]
    else:
        closes = [100.0 + (1 if index % 2 else -1) for index in range(28)] + [97.8]
        prices = [(close + 0.1, close + 0.2, close - 0.2, close) for close in closes]
        prices[-1] = (97.9, 100.0, 97.7, 97.8)
    rows = tuple(Candle(ASSETS[0], start_ms + index * BAR_MS, BAR_MS,
                        (start_ms + (index + 1) * BAR_MS) * MS_NS,
                        start_ms + (index + 1) * BAR_MS, *price, True)
                 for index, price in enumerate(prices))
    offer = Offer(ASSETS[0], 'turbo-option', decision_ns, decision_ms, 0.85,
                  decision_ms + BAR_MS, decision_ms + 90000, True, 'supported')
    quote = Quote(ASSETS[0], decision_ns, decision_ms, 100.0)
    return decision_ns, offer, quote, rows


class CandleIdentityTests(unittest.TestCase):
    def act(self, policy, data, rows=None, delta_ns=0):
        decision_ns, offer, quote, original_rows = data
        return decide(policy, ASSETS[0], decision_ns + delta_ns, offer, quote,
                      original_rows if rows is None else rows)

    def test_independent_positive_shapes_for_both_fixed_rules(self):
        for policy, expected in zip(POLICIES, ('put', 'call')):
            with self.subTest(policy=policy):
                self.assertEqual(self.act(policy, positive_inputs(policy)).direction, expected)

    def test_all_six_old_identity_conflict_orders_reject_after_later_revision(self):
        for policy in POLICIES:
            data = positive_inputs(policy)
            rows = data[-1]
            a = rows[-1]
            b = replace(a, open=a.open + 0.01)
            c = replace(a, received_ns=a.received_ns + 1)
            for index, order in enumerate(permutations((a, b, c))):
                with self.subTest(policy=policy, permutation=index):
                    with self.assertRaisesRegex(InvalidInput, 'conflicting candle version'):
                        self.act(policy, data, rows[:-1] + order, delta_ns=1)

    def test_distant_identity_conflicts_reject_outside_29_bar_window(self):
        for policy in POLICIES:
            data = positive_inputs(policy, offset_bars=80)
            a = replace(data[-1][0], start_ms=0, received_ns=BAR_MS * MS_NS,
                        broker_at_receipt_ms=BAR_MS)
            b = replace(a, close=a.close + 0.01)
            c = replace(a, received_ns=a.received_ns + 1)
            for index, order in enumerate(permutations((a, b, c))):
                with self.subTest(policy=policy, permutation=index):
                    with self.assertRaisesRegex(InvalidInput, 'conflicting candle version'):
                        self.act(policy, data, order + data[-1])

    def test_distinct_receipts_and_identical_duplicates_preserve_selected_evidence(self):
        for policy in POLICIES:
            data = positive_inputs(policy)
            a = data[-1][-1]
            prior = replace(a, received_ns=a.received_ns - 1, open=a.open + 0.01)
            expected = self.act(policy, data)
            for index, order in enumerate(permutations((a, prior, a))):
                with self.subTest(policy=policy, permutation=index):
                    self.assertEqual(self.act(policy, data, data[-1][:-1] + order), expected)

    def test_future_forming_and_unrelated_asset_conflicts_do_not_enter_identity_set(self):
        for policy in POLICIES:
            data = positive_inputs(policy)
            a = data[-1][-1]
            future = replace(a, received_ns=data[0] + 1, open=math.nan)
            future_conflict = replace(future, close=math.inf)
            forming = replace(a, finalized=False, open=math.nan)
            unrelated = replace(a, asset=ASSETS[1], close=math.inf)
            expected = self.act(policy, data)
            for extra in ((future, future_conflict), (forming,), (unrelated,)):
                for rows in (extra + data[-1], data[-1] + extra):
                    with self.subTest(policy=policy, extra=extra):
                        self.assertEqual(self.act(policy, data, rows), expected)

    def test_causal_finalized_identity_conflict_precedes_version_eligibility_filters(self):
        for policy in POLICIES:
            data = positive_inputs(policy)
            a = data[-1][-1]
            for b in (replace(a, clock_status='unknown'),
                      replace(a, duration_ms=60000),
                      replace(a, broker_at_receipt_ms=a.broker_at_receipt_ms - 1)):
                for order in ((a, b), (b, a)):
                    with self.subTest(policy=policy, conflict=b):
                        with self.assertRaisesRegex(InvalidInput, 'conflicting candle version'):
                            self.act(policy, data, data[-1][:-1] + order)


if __name__ == '__main__':
    unittest.main()
