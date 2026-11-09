"""Numeric rejection stays inside the exported InvalidInput contract."""
from dataclasses import replace
import math
import sys
import unittest

from ..contracts import ASSETS, POLICIES, Candle, InvalidInput, Offer, Quote, number
from ..policy import canonical, decide
from .test_candle_identity import positive_inputs


def exhaustion_inputs(put=False, scale=1.0):
    data = positive_inputs(POLICIES[1])
    rows = []
    for index, item in enumerate(data[-1]):
        close = (9.5 if index % 2 == 0 else 10.5) if index < 28 else 9.0
        open_ = close if index < 28 else 9.5
        if put:
            open_, close = 20.0 - open_, 20.0 - close
        rows.append(replace(item, open=open_ * scale, high=12.0 * scale,
                            low=8.0 * scale, close=close * scale))
    quote = replace(data[2], price=rows[-1].close)
    return data[0], data[1], quote, tuple(rows)


class NumericContractTests(unittest.TestCase):
    def act(self, policy, data):
        return decide(policy, ASSETS[0], *data)

    def assert_typed_rejection(self, call):
        try:
            call()
        except InvalidInput:
            return
        except Exception as error:
            self.fail('escaping exception outside InvalidInput contract: ' + type(error).__name__)
        self.fail('numeric input did not raise InvalidInput')

    def test_huge_signed_numbers_raise_documented_invalid_input(self):
        for value in (10 ** 400, -(10 ** 400)):
            with self.subTest(sign=value > 0):
                self.assert_typed_rejection(lambda: number(value, 'huge exact integer'))

    def test_huge_integer_numeric_fields_reject_for_both_fixed_rules(self):
        for policy in POLICIES:
            decision_ns, offer, quote, rows = positive_inputs(policy)
            altered = [(decision_ns, replace(offer, payout=10 ** 400), quote, rows),
                       (decision_ns, offer, replace(quote, price=10 ** 400), rows)]
            for field in ('open', 'high', 'low', 'close'):
                altered.append((decision_ns, offer, quote,
                                rows[:-1] + (replace(rows[-1], **{field: 10 ** 400}),)))
            for index, data in enumerate(altered):
                with self.subTest(policy=policy, field=index):
                    self.assert_typed_rejection(lambda: self.act(policy, data))

    def test_finite_positive_exhaustion_overflow_raises_invalid_input_for_both_directions(self):
        for put, expected in ((False, 'call'), (True, 'put')):
            self.assertEqual(self.act(POLICIES[1], exhaustion_inputs(put)).direction, expected)
            scaled = exhaustion_inputs(put, 1e156)
            self.assertTrue(all(math.isfinite(getattr(row, name)) and getattr(row, name) > 0
                                for row in scaled[-1] for name in ('open', 'high', 'low', 'close')))
            with self.subTest(put=put):
                self.assert_typed_rejection(lambda: self.act(POLICIES[1], scaled))

    def test_largest_finite_quote_and_payout_keep_original_admission_semantics(self):
        for policy in POLICIES:
            decision_ns, offer, quote, rows = positive_inputs(policy)
            expected = self.act(policy, (decision_ns, offer, quote, rows))
            value = self.act(policy, (decision_ns, offer, replace(quote, price=sys.float_info.max), rows))
            self.assertEqual(value.direction, expected.direction)
            self.assertEqual(value.reason, expected.reason)
            value = self.act(policy, (decision_ns, replace(offer, payout=sys.float_info.max), quote, rows))
            self.assertEqual(value.reason, 'payout_below_floor_or_invalid')

    def test_unencodable_numeric_evidence_raises_invalid_input(self):
        old_limit = sys.get_int_max_str_digits()
        try:
            sys.set_int_max_str_digits(4300)
            self.assert_typed_rejection(lambda: canonical({'exact_integer_exceeds_json_digit_limit': 10 ** 5000}))
        finally:
            sys.set_int_max_str_digits(old_limit)


if __name__ == '__main__':
    unittest.main()
