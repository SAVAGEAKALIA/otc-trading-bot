"""Deterministic gate tests and scenario evals for the audit's claims."""
import unittest
from carry_audit import funding_proxy, minimum_capital, required_annual_funding


class GateTests(unittest.TestCase):
    def test_segregated_one_x_needs_two_n(self):
        self.assertEqual(minimum_capital(1000, 1, 100), 2100)

    def test_invalid_assumptions_rejected(self):
        with self.assertRaises(ValueError):
            minimum_capital(100, 0)

    def test_entry_cannot_use_current_day_funding(self):
        result = funding_proxy([0.0] * 7 + [1.0], .0031)
        self.assertFalse(any(p[1] for p in result))

    def test_entry_fee_and_lag(self):
        result = funding_proxy([.001] * 8, .0031)
        self.assertEqual(sum(p[1] for p in result), 1)
        self.assertAlmostEqual(result[-1][0], .001 - .0031 / 2)

    def test_three_day_exit_is_lagged(self):
        result = funding_proxy([.001] * 8 + [-.002] * 5, .0031)
        self.assertTrue(result[8][1])
        self.assertFalse(result[10][1])


class ScenarioEvals(unittest.TestCase):
    def test_fee_horizon_gate_conflicts_with_eight_percent(self):
        for cost in [.0031, .0023]:
            with self.subTest(cost=cost):
                self.assertGreater(required_annual_funding(cost), .08)
                self.assertAlmostEqual(required_annual_funding(cost)*7/365, 2*cost)

    def test_constant_funding_and_open_terminal_position(self):
        for rate in [0, .00001, .001, -.001]:
            with self.subTest(rate=rate):
                output = funding_proxy([rate]*365, .0031)
                if rate*365 > .08:
                    self.assertAlmostEqual(sum(p[0] for p in output), rate*358-.0031/2)
                    self.assertTrue(output[-1][1])
                else:
                    self.assertEqual(sum(p[0] for p in output), 0)

    def test_capital_sensitivity(self):
        for leverage in [1, 1.5, 2]:
            with self.subTest(leverage=leverage):
                capital = minimum_capital(1000, leverage)
                self.assertGreater(capital, 1000)
                self.assertAlmostEqual(capital - 1000, 1000/leverage)


if __name__ == '__main__':
    unittest.main()
