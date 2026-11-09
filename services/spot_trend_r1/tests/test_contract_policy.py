"""Contract regressions attack policy content, shape and exact numeric semantics."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from fractions import Fraction as F
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE))
import plan


def replace_at(contract, path, value):
    if not path:
        return value
    candidate = contract.copy()
    parent = candidate
    for key in path[:-1]:
        parent[key] = parent[key].copy()
        parent = parent[key]
    parent[path[-1]] = value
    return candidate


class ContractPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = plan.read_json((SERVICE / 'contracts' / 'protocol.json').read_bytes())

    def test_reported_policy_attacks_are_rejected(self):
        attacks = [
            (('allocation', 'transfers_between_components'), 'allowed'),
            (('execution', 'retry_policy'), 'retry on every daily decision'),
            (('terminal', 'closing_valuation'), 'midnight before terminal submission'),
            (('accounting', 'b0'), 'fixed USDT=USD=1'),
            (('fee_rate',), 0),
            (('live_trading_authorized',), True),
        ]
        for path, value in attacks:
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    plan.validate_contract(replace_at(self.contract, path, value))

    def test_policy_evidence_and_scope_leaves_are_rejected_if_changed(self):
        for path, replacement in [
                (('signals', 'availability'), 'retrieved later means available'),
                (('valuation', 'holes'), 'forward fill missing marks'),
                (('evidence', 'full_day_semantics'), 'verified'),
                (('unknown_account_facts',), []),
                (('forbidden',), []),
                (('evaluation', 'critical_scenario_pass_fraction'), '0.9')]:
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    plan.validate_contract(replace_at(self.contract, path, replacement))

    def test_top_level_and_nested_object_additions_are_rejected(self):
        for path in ((), ('allocation', 'each_component_weight'), ('execution',), ('live_risk_budgets',)):
            value = self.contract
            for key in path:
                value = value[key]
            changed = dict(value, unsupported_policy={'live_trading_authorized': True})
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    plan.validate_contract(replace_at(self.contract, path, changed))

    def test_missing_top_level_and_nested_fields_are_rejected_before_lookup(self):
        for path, key in (((), 'r2_authorized'), (('allocation',), 'transfers_between_components'),
                          (('terminal',), 'closing_valuation')):
            value = self.contract
            for parent in path:
                value = value[parent]
            changed = value.copy()
            del changed[key]
            with self.subTest(path=path + (key,)):
                with self.assertRaises(ValueError):
                    plan.validate_contract(replace_at(self.contract, path, changed))

    def test_container_numerical_and_type_substitutions_are_rejected(self):
        alternatives = [
            (('execution', 'quote_wait_ms'), 60000.0),
            (('execution', 'quote_wait_ms'), '60000'),
            (('valuation', 'max_age_ms'), 60000.0),
            (('allocation', 'each_component_weight', 'numerator'), True),
            (('allocation', 'each_component_weight', 'numerator'), 1.0),
            (('allocation', 'each_symbol_weight', 'numerator'), True),
            (('r2_authorized',), 0),
            (('evaluation', 'deterministic_only'), 1),
            (('capital_budget_usdt',), False),
            (('live_risk_budgets', 'max_loss_usdt'), 0),
            (('symbols',), tuple(self.contract['symbols'])),
            (('lookbacks',), tuple(self.contract['lookbacks'])),
            (('allocation',), list(self.contract['allocation'].items())),
            (('signals', 'entry'), None),
            ((), None), ((), []),
        ]
        for path, alternative in alternatives:
            with self.subTest(path=path, substituted_type=type(alternative).__name__):
                with self.assertRaises(ValueError):
                    plan.validate_contract(replace_at(self.contract, path, alternative))

    def test_semantic_reformatting_is_accepted_and_does_not_mutate_policy(self):
        def reverse_keys(value):
            if type(value) is dict:
                return {key: reverse_keys(value[key]) for key in reversed(list(value))}
            if type(value) is list:
                return [reverse_keys(child) for child in value]
            return value

        formatted = json.dumps(reverse_keys(self.contract), indent=4, ensure_ascii=True).encode()
        candidate = plan.read_json(formatted)
        before = deepcopy(candidate)
        plan.validate_contract(candidate)
        self.assertEqual(candidate, before)
        self.assertEqual(candidate, self.contract)

    def test_cli_attack_exits_two_with_no_stdout_before_source_interpretation(self):
        attack = deepcopy(self.contract)
        attack['allocation']['transfers_between_components'] = 'allowed'
        attack['execution']['retry_policy'] = 'retry daily'
        attack['terminal']['closing_valuation'] = 'before the final sale'
        attack['accounting']['b0'] = 'USDT=USD=1'
        attack['fee_rate'] = 0
        attack['live_trading_authorized'] = True
        with tempfile.TemporaryDirectory() as directory:
            contract_path = Path(directory) / 'attack.json'
            raw = json.dumps(attack).encode()
            contract_path.write_bytes(raw)

            def contract_read_only(path):
                self.assertEqual(path, contract_path, 'source interpreted before policy validation')
                return raw

            stdout, stderr = io.StringIO(), io.StringIO()
            old_argv, old_read = sys.argv, Path.read_bytes
            try:
                sys.argv = ['plan.py', '--contract', str(contract_path),
                            '--source-dir', str(Path(directory) / 'not-read')]
                Path.read_bytes = contract_read_only
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as rejected:
                        plan.main()
            finally:
                sys.argv, Path.read_bytes = old_argv, old_read
            self.assertEqual(rejected.exception.code, 2)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn('INPUT_REJECTED:', stderr.getvalue())

    def test_tiny_overspend_is_rejected_without_rounding_to_cash(self):
        excess = F(1, 10**80)
        with self.assertRaisesRegex(ValueError, 'borrow'):
            plan.apply_fill(plan.Ledger(F(1)), 'tiny-overdraft', 'buy', '1',
                            str(F(1) + excess), 'USDT', '0')

    def test_tiny_base_fee_is_retained_exactly(self):
        fee = F(1, 10**80)
        bought = plan.apply_fill(plan.Ledger(F(1)), 'tiny-base-fee', 'buy', '1', '1', 'BASE', str(fee))
        self.assertEqual(bought.cash, F(0))
        self.assertEqual(bought.quantity, F(1) - fee)
        self.assertEqual(F(1) - bought.quantity, fee)
        self.assertLess(bought.quantity, F(1))


if __name__ == '__main__':
    unittest.main()
