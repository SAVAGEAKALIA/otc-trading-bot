from decimal import Decimal
import unittest

from carry_cost_screen import DAY_MS, clears, window_bps


class CarryCostTest(unittest.TestCase):
    def test_strict_gate_and_other_costs(self):
        self.assertFalse(clears(Decimal('62'), Decimal('31')))
        self.assertTrue(clears(Decimal('62.01'), Decimal('31')))
        self.assertFalse(clears(Decimal('62.01'), Decimal('31'), Decimal('.01')))

    def test_window_includes_left_excludes_right(self):
        cutoff = 8 * DAY_MS
        events = [(DAY_MS - 1, Decimal('1')), (DAY_MS, Decimal('.0002')),
                  (cutoff - 1, Decimal('-.0001')), (cutoff, Decimal('1'))]
        self.assertEqual(window_bps(events, cutoff), Decimal('1'))
