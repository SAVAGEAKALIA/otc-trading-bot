"""Local gate tests; all inputs are saved reports or synthetic exact balances."""
from copy import deepcopy
from fractions import Fraction as F
import os
from pathlib import Path
import sys
import tempfile
import unittest

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE))
import plan

SOURCE = Path(os.environ.get('D3_SOURCE_DIR', 'docs/research/crypto-r1-2026-10-31')).resolve()


class PlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.preview = plan.read_json((SOURCE / 'spot_trend_preview.json').read_bytes())
        cls.quotes = plan.read_json((SOURCE / 'spot_quote_checks.json').read_bytes())
        cls.contract = plan.read_json((SERVICE / 'contracts/protocol.json').read_bytes())

    def test_frozen_source_identity_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            for filename in plan.SOURCE_HASHES:
                raw = (SOURCE / filename).read_bytes()
                Path(directory, filename).write_bytes(raw + b' ')
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                plan.run(Path(directory))

    def test_json_duplicates_nonfinite_and_fraction_floats_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.assertRaises(ValueError):
                plan.read_json(raw)
        for value in (True, 1.0, 'NaN', '-1', '1/0'):
            with self.assertRaises(ValueError):
                plan.rational(value)

    def test_protocol_budget_weight_and_promotion_failures(self):
        for path, value in [(('capital_budget_usdt',), 100), (('r2_authorized',), True),
                            (('r2_freeze_ready',), True), (('returns_computed',), True),
                            (('execution', 'quote_wait_ms'), 60001),
                            (('allocation', 'rebalance'), 'daily'),
                            (('allocation', 'each_component_weight'), {'numerator': 166667, 'denominator': 1000000})]:
            candidate = deepcopy(self.contract)
            target = candidate
            for item in path[:-1]: target = target[item]
            target[path[-1]] = value
            with self.assertRaises(ValueError, msg=str(path)):
                plan.validate_contract(candidate)

    def test_exact_weight_reconciliation(self):
        weights = [F(1, 6)] * len(plan.validate_preview(self.preview))
        self.assertEqual(sum(weights), 1)
        ledgers = {f'{s}:{e}/{x}': plan.Ledger(F(1, 6)) for s, e, x in plan.validate_preview(self.preview)}
        totals = plan.reconcile_components(ledgers)
        self.assertEqual(totals['portfolio_cash_usdt'], 1)
        self.assertTrue(all(x['cash_usdt'] == F(1, 2) for x in totals['symbols'].values()))
        ledgers.pop(next(iter(ledgers)))
        with self.assertRaises(ValueError): plan.reconcile_components(ledgers)

    def test_preview_component_identity_and_grid_failures(self):
        mutations = [lambda x: x['results'].pop('ETHUSDT'),
                     lambda x: x['results']['BTCUSDT'].pop(),
                     lambda x: x['results']['BTCUSDT'].append(x['results']['BTCUSDT'][0]),
                     lambda x: x['results']['BTCUSDT'][0].update(entry_lookback=21),
                     lambda x: x['results']['BTCUSDT'][0].update(eligible_signal_days=89),
                     lambda x: x.update(decision_last='2026-10-30T00:05:00Z'),
                     lambda x: x['source']['records'][0].update(rows=189),
                     lambda x: x['source']['records'][0].update(sha256='wrong'),
                     lambda x: x['source']['records'][0].update(url='https://unrelated.test/')]
        for mutation in mutations:
            candidate = deepcopy(self.preview); mutation(candidate)
            with self.assertRaises(ValueError): plan.validate_preview(candidate)

    def test_threshold_dates_malformed_duplicate_outside_conflicting(self):
        for value in (['2026-02-30'], ['2026-8-02'], ['2026-08-01'], ['2026-10-31'],
                      ['2026-08-19', '2026-08-19'], ['2026-08-20', '2026-08-19']):
            candidate = deepcopy(self.preview)
            candidate['results']['BTCUSDT'][0]['entry_condition_dates'] = value
            with self.assertRaises(ValueError): plan.validate_preview(candidate)
        candidate = deepcopy(self.preview)
        candidate['results']['BTCUSDT'][0]['exit_condition_dates'] = ['2026-08-19']
        with self.assertRaises(ValueError): plan.validate_preview(candidate)

    def test_quotes_all_checked_and_invalid_fields_rejected(self):
        components = plan.validate_preview(self.preview)
        mutations = [lambda x: x['rows'].pop(), lambda x: x['rows'].append(x['rows'][0]),
                     lambda x: x['rows'][0].update(symbol='SOLUSDT'),
                     lambda x: x['rows'][0].update(target_ms=0),
                     lambda x: x['rows'][0].update(offset_ms=0),
                     lambda x: x['rows'][0].update(bid='NaN'),
                     lambda x: x['rows'][0].update(ask=x['rows'][0]['bid']),
                     lambda x: x['rows'][0].update(bid_size='0'),
                     lambda x: x['rows'][0].update(archive_sha256='unknown'),
                     lambda x: x.update(fills_simulated=True)]
        for mutation in mutations:
            candidate = deepcopy(self.quotes); mutation(candidate)
            with self.assertRaises(ValueError): plan.validate_quotes(candidate, components)

    def test_execution_quote_exact_boundaries(self):
        for offset, accepted in ((-1, False), (0, True), (60000, True), (60001, False)):
            self.assertEqual(plan.quote_in_window(100000 + offset, 100000), accepted)

    def test_valuation_exact_age_and_availability(self):
        for offset, accepted in ((-60001, False), (-60000, True), (-1, True), (0, False), (1, False)):
            self.assertEqual(plan.valuation_in_window(100000 + offset, 100000), accepted)
        for event, available, expected in ((99, None, False), (99, 100, False), (100, 99, False),
                                           (99, 99, True), (100, 101, False)):
            self.assertEqual(plan.available_before(event, available, 100), expected)

    def test_initial_exit_repeated_entry_equality_and_partial_entry(self):
        self.assertEqual(plan.intended_action(F(0), False, True), 'none')
        self.assertEqual(plan.intended_action(F(1), True, False), 'none')
        self.assertEqual(plan.target_after('long', False, False), 'long')
        self.assertEqual(plan.intended_action(F(0), False, False), 'none')
        self.assertEqual(plan.intended_action(F(0), True, False), 'buy')
        partial = plan.apply_fill(plan.Ledger(F(100)), 'p', 'buy', '1', '10', 'BASE', '0.1')
        self.assertEqual(partial.quantity, F(9, 10))
        self.assertEqual(partial.cash, 90)
        self.assertEqual(plan.intended_action(partial.quantity, True, False), 'none')

    def test_fee_inclusive_cash_base_and_third_currency_conservation(self):
        initial = plan.Ledger(F(101))
        bought = plan.apply_fill(initial, 'b', 'buy', '10', '10', 'USDT', '1')
        self.assertEqual((bought.cash, bought.quantity), (0, 10))
        with self.assertRaises(ValueError): plan.apply_fill(plan.Ledger(F(100)), 'b', 'buy', '10', '10', 'USDT', '1')
        sold = plan.apply_fill(bought, 's', 'sell', '9', '10', 'BASE', '1')
        self.assertEqual((sold.cash, sold.quantity), (90, 0))
        with self.assertRaises(ValueError): plan.apply_fill(sold, 's', 'sell', '1', '10', 'USDT', '0')
        other = plan.Ledger(F(100), other=(('FEE', F(2)),))
        after = plan.apply_fill(other, 'x', 'buy', '5', '10', 'FEE', '1')
        self.assertEqual(after.other, (('FEE', F(1)),))
        with self.assertRaises(ValueError): plan.apply_fill(plan.Ledger(F(100)), 'b', 'buy', '1', '10', 'FEE', '1')

    def test_failed_and_partial_exits_preserve_exposure_and_terminal_block(self):
        initial = plan.Ledger(F(0), F(10))
        self.assertEqual(plan.intended_action(initial.quantity, False, True), 'sell')
        self.assertEqual(initial.quantity, 10)  # No fill outcome means no mutation.
        partial = plan.apply_fill(initial, 's', 'sell', '4', '10', 'USDT', '1')
        self.assertEqual(partial.quantity, 6)
        self.assertEqual(plan.intended_action(partial.quantity, False, True), 'sell')
        self.assertEqual(plan.intended_action(partial.quantity, False, False), 'none')
        self.assertEqual(plan.intended_action(partial.quantity, False, False, terminal=True), 'sell')
        flat = [plan.Ledger(F(1))] * 6
        self.assertEqual(plan.terminal_state(flat, True), 'flat_reconciled')
        self.assertEqual(plan.terminal_state(flat, False), 'blocked_unresolved_continuation')
        self.assertEqual(plan.terminal_state(flat[:5] + [partial], True), 'blocked_unresolved_continuation')
        with self.assertRaises(ValueError): plan.terminal_state([], True)

if __name__ == '__main__':
    unittest.main()
