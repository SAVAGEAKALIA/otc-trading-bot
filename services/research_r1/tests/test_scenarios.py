import importlib.util
from pathlib import Path
import unittest
import json
import subprocess
import sys
import tempfile

spec = importlib.util.spec_from_file_location('scenarios', Path(__file__).resolve().parents[1] / 'scenarios.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EconomicsTests(unittest.TestCase):
    def test_cli_csv_uses_portable_lf_line_endings(self):
        with tempfile.TemporaryDirectory() as root:
            config = Path(root) / 'config.json'; output = Path(root) / 'scenarios.csv'
            config.write_text(json.dumps(module.example_config()))
            subprocess.run([sys.executable, str(Path(module.__file__)), '--config', str(config), '--output', str(output)], check=True, capture_output=True)
            self.assertNotIn(b'\r', output.read_bytes())
            self.assertTrue(output.read_bytes().endswith(b'\n'))

    def test_two_legs_and_reserve(self):
        row = module.economics('2200', '.10', annual_fixed_cost='100', reserve_per_notional='.2')
        self.assertEqual(row['hedged_notional'], '1000')
        self.assertEqual(row['annual_net_profit'], '0')
        self.assertEqual(row['capital_multiplier'], '2.2')

    def test_fixed_cost_changes_economic_sign(self):
        self.assertLess(module.D(module.economics('1000', '.10', annual_fixed_cost='120')['annual_net_profit']), 0)
        self.assertGreater(module.D(module.economics('10000', '.10', annual_fixed_cost='120')['annual_net_profit']), 0)

    def test_no_finite_breakeven_when_pre_fixed_excess_nonpositive(self):
        self.assertIsNone(module.economics('1000', '.02', benchmark_apr='.02')['break_even_capital'])

    def test_annual_cost_not_deducted_twice(self):
        row = module.economics('2000', '.10', annual_fixed_cost='20', reserve_per_notional='0')
        self.assertEqual(row['annual_net_profit'], '80')
        self.assertEqual(row['net_capital_apr'], '0.04')

    def test_bad_values_reject(self):
        for capital in ['NaN', 'Infinity', '-1', '0', True]:
            with self.subTest(capital=capital), self.assertRaises(ValueError):
                module.economics(capital, '.10')
        for args in [{'short_leverage': '0'}, {'short_leverage': '2'}, {'annual_fixed_cost': '-1'}, {'reserve_per_notional': '-1'}]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                module.economics('1000', '.10', **args)

    def test_bad_scenario_rejected_before_readiness(self):
        for field, value in [('scenario_capital_usdt', ['-1']), ('scenario_net_notional_apr', ['NaN']), ('scenario_annual_fixed_cost_usdt', ['-1']), ('scenario_short_leverage', '0')]:
            config = module.example_config(); config[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                module.configuration_status(config)

    def test_research_flags_cannot_sign_experiment(self):
        config = module.example_config()
        for key in ['capital_budget_usdt', 'max_loss_usdt', 'max_drawdown_pct', 'venue_loss_budget_usdt', 'stablecoin_loss_budget_usdt', 'risk_premium_bps', 'minimum_profit_usdt_year']:
            config[key] = '1'
        for key in ['eligibility_verified', 'fees_verified', 'data_quality_passed', 'trial_spec_signed']:
            config[key] = True
        status = module.configuration_status(config)
        self.assertTrue(status['configuration_complete'])
        self.assertFalse(status['r2_freeze_ready'])
        self.assertFalse(status['live_enabled'])

    def test_negative_funding_allowed_as_loss_scenario(self):
        self.assertLess(module.D(module.economics('1000', '-.10')['annual_net_profit']), 0)


class ConfigurationTests(unittest.TestCase):
    def config(self):
        return module.example_config()

    def test_null_budgets_are_not_ready(self):
        status = module.configuration_status(self.config())
        self.assertFalse(status['r2_freeze_ready'])
        self.assertIn('capital_budget_usdt', status['unresolved'])
        self.assertFalse(status['live_enabled'])

    def test_r1_can_never_enable_live(self):
        config = self.config(); config['live_enabled'] = True
        with self.assertRaises(ValueError): module.configuration_status(config)

    def test_negative_or_nan_budget_rejected(self):
        for bad in ['-1', 'NaN', '0']:
            config = self.config(); config['max_loss_usdt'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError): module.configuration_status(config)

    def test_fee_entry_cannot_be_smuggled_as_verified(self):
        config = self.config(); config['fees_verified'] = 'yes'
        with self.assertRaises(ValueError): module.configuration_status(config)


if __name__ == '__main__': unittest.main()
