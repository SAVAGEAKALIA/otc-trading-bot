"""Deterministic eval lane. Frozen threshold: every critical scenario must pass."""
import argparse
from datetime import date, timedelta
from fractions import Fraction as F
import json
from pathlib import Path
import random
import sys
import time
import unittest

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE))
import plan
from test_full_plan import FullReportTests, SOURCE
from policy_mutations import evaluate as evaluate_policy_mutations
from output_ownership import evaluate as evaluate_output_ownership
from delivery_checks import evaluate as evaluate_delivery


def evaluate_fraction_extremes(rng):
    """Exact integer/Fraction oracle around decimal-context precision boundaries."""
    magnitudes = sorted({1, 2, 6, 18, 27, 28, 29, 30, 80, 128, 256, 512}
                        | set(rng.sample(range(3, 513), 96)))
    counts = {'over_cash_consideration': 0, 'tiny_quote_fee_overdraft': 0,
              'exact_tiny_base_fee': 0, 'exact_tiny_quote_fee': 0,
              'base_fee_overdraft': 0, 'exact_sell_base_fee': 0,
              'grid_floor_affordability': 0, 'grid_next_step_rejection': 0}

    def rejected(ledger, identity, side, quantity, price, fee_currency, fee):
        try:
            plan.apply_fill(ledger, identity, side, quantity, price, fee_currency, fee)
        except ValueError:
            return
        raise AssertionError('exact over-balance debit accepted: ' + identity)

    for digits in magnitudes:
        denominator = 10**digits
        epsilon = F(1, denominator)
        fee_text = f'1e-{digits}'
        price_text = '1.' + '0' * (digits - 1) + '1'
        rejected(plan.Ledger(F(1)), f'price-over:{digits}', 'buy', '1', price_text, 'USDT', '0')
        counts['over_cash_consideration'] += 1
        rejected(plan.Ledger(F(1)), f'fee-over:{digits}', 'buy', '1', '1', 'USDT', fee_text)
        counts['tiny_quote_fee_overdraft'] += 1
        base_fee = plan.apply_fill(plan.Ledger(F(1)), f'base:{digits}', 'buy', '1', '1', 'BASE', fee_text)
        assert base_fee.cash == F(0) and base_fee.quantity == F(1) - epsilon
        assert F(1) - base_fee.quantity == epsilon
        counts['exact_tiny_base_fee'] += 1
        quote_fee = plan.apply_fill(plan.Ledger(F(1) + epsilon), f'quote:{digits}',
                                    'buy', '1', '1', 'USDT', fee_text)
        assert quote_fee.cash == F(0) and quote_fee.quantity == F(1)
        counts['exact_tiny_quote_fee'] += 1
        rejected(plan.Ledger(F(0), F(1)), f'base-over:{digits}', 'sell', '1', '1', 'BASE', fee_text)
        counts['base_fee_overdraft'] += 1
        sold = plan.apply_fill(plan.Ledger(F(0), F(1) + epsilon), f'sell:{digits}',
                               'sell', '1', '1', 'BASE', fee_text)
        assert sold.cash == F(1) and sold.quantity == F(0)
        counts['exact_sell_base_fee'] += 1
        # Pure integer oracle for the largest fully paid synthetic grid order.
        # A repeating 1/7 cannot be made affordable by rounded decimal equality.
        units = denominator // 7
        grid_quantity = F(units, denominator)
        floor_fill = plan.apply_fill(plan.Ledger(F(1)), f'floor:{digits}', 'buy',
                                    str(grid_quantity), '7', 'USDT', '0')
        assert floor_fill.quantity == grid_quantity
        assert floor_fill.cash == F(denominator - 7 * units, denominator)
        counts['grid_floor_affordability'] += 1
        rejected(plan.Ledger(F(1)), f'next-grid:{digits}', 'buy',
                 str(F(units + 1, denominator)), '7', 'USDT', '0')
        counts['grid_next_step_rejection'] += 1
    return {'status': 'PASS', 'threshold': 'all critical scenarios pass (100%)',
            'magnitudes': magnitudes, 'smallest_fee': str(F(1, 10**max(magnitudes))),
            'cases_by_category': counts, 'total': sum(counts.values()), 'failed': 0,
            'oracle': 'exact Fraction balances and independent integer grid floor'}


def run(policy_evidence: Path | None = None, ownership_evidence: Path | None = None):
    started = time.perf_counter()
    rng = random.Random(20261105)
    counts = {'state_and_conservation_trajectories': 0, 'temporal_boundary_cases': 0,
              'fee_currency_cases': 0, 'terminal_flatness_cases': 0}
    # Separate integer-cent/base-hundredth oracle, with partial/missed/full outcomes.
    # It has no dependency on planner state, signal target or price history.
    for case in range(256):
        cash_cents, base_hundredths = 100000, 0
        ledger = plan.Ledger(F(cash_cents, 100))
        signal_target = 'flat'
        for step in range(24):
            condition = rng.choice(('hold', 'entry', 'exit'))
            entry, exit_ = condition == 'entry', condition == 'exit'
            prior_target = signal_target
            if condition == 'entry': signal_target = 'long'
            if condition == 'exit': signal_target = 'flat'
            assert plan.target_after(prior_target, entry, exit_) == signal_target
            expected = 'none'
            if base_hundredths == 0 and condition == 'entry': expected = 'buy'
            if base_hundredths > 0 and condition == 'exit': expected = 'sell'
            assert plan.intended_action(ledger.quantity, entry, exit_) == expected
            outcome = rng.choice(('missed', 'partial', 'full'))
            before = ledger
            if expected != 'none' and outcome != 'missed':
                price = rng.randint(1, 100)
                maximum = max(0, (cash_cents - 1) // price) if expected == 'buy' else base_hundredths
                amount = maximum if outcome == 'full' else maximum // 2
                if amount:
                    if expected == 'buy':
                        cash_cents -= amount * price + 1
                        base_hundredths += amount
                    else:
                        cash_cents += amount * price - 1
                        base_hundredths -= amount
                    ledger = plan.apply_fill(ledger, f'{case}:{step}', expected, str(F(amount, 100)), str(price), 'USDT', '0.01')
            else:
                assert ledger == before
            assert ledger.cash == F(cash_cents, 100)
            assert ledger.quantity == F(base_hundredths, 100)
            assert cash_cents >= 0 and base_hundredths >= 0
            # A holding on an equality/hold day stays owned, irrespective of target.
            assert plan.intended_action(ledger.quantity, False, False) == 'none'
        counts['state_and_conservation_trajectories'] += 1
    # Generated UTC calendar points cross month/year/leap-day boundaries. Oracle uses
    # day differences from the Unix epoch, independently of planner timestamp helpers.
    for sample in range(128):
        day = date(2024, 1, 1) + timedelta(days=rng.randrange(1200))
        midnight = (day - date(1970, 1, 1)).days * 86400000
        assert plan.milliseconds(plan.utc(day)) == midnight
        for offset, expected in ((-60001, False), (-60000, True), (-1, True), (0, False), (1, False)):
            assert plan.valuation_in_window(midnight + offset, midnight) is expected
            counts['temporal_boundary_cases'] += 1
        for offset, expected in ((-1, False), (0, True), (59999, True), (60000, True), (60001, False)):
            assert plan.quote_in_window(midnight + 600000 + offset, midnight + 600000) is expected
            counts['temporal_boundary_cases'] += 1
        assert not plan.available_before(midnight - 1, None, midnight)
        assert not plan.available_before(midnight - 1, midnight, midnight)
        assert plan.available_before(midnight - 1, midnight - 1, midnight)
        counts['temporal_boundary_cases'] += 3
    # Base and quote currency costs are counted once; external cost funds are never created.
    for case in range(128):
        q, fee, price = rng.randint(2, 100), rng.randint(1, 99), rng.randint(1, 100)
        fee = F(fee, 100)
        original = plan.Ledger(F(q * price) + fee)
        bought = plan.apply_fill(original, f'b{case}', 'buy', str(q), str(price), 'USDT', str(fee))
        assert bought.cash == 0 and bought.quantity == q
        sold = plan.apply_fill(bought, f's{case}', 'sell', str(F(q) - fee), str(price), 'BASE', str(fee))
        assert sold.quantity == 0 and sold.cash == (q - fee) * price
        try:
            plan.apply_fill(bought, f'b{case}', 'buy', '1', '1', 'USDT', '0')
        except ValueError:
            pass
        else:
            raise AssertionError('duplicate actual fill charged twice')
        counts['fee_currency_cases'] += 1
    flat = [plan.Ledger(F(1)) for _ in range(6)]
    for component in range(6):
        for residue in (F(0), F(1, 10**18), F(1, 2), F(1)):
            for known in (False, True):
                ledgers = flat.copy()
                ledgers[component] = plan.Ledger(F(1), residue)
                expected = 'flat_reconciled' if known and residue == 0 else 'blocked_unresolved_continuation'
                assert plan.terminal_state(ledgers, known) == expected
                counts['terminal_flatness_cases'] += 1
    exactness = evaluate_fraction_extremes(rng)
    counts['exact_arithmetic_boundary_cases'] = exactness['total']
    policy = evaluate_policy_mutations(SOURCE)
    if policy_evidence is not None:
        policy_evidence.write_text(json.dumps(policy, indent=2, sort_keys=True) + '\n')
    counts['policy_mutation_cases'] = policy['total']
    ownership = evaluate_output_ownership(SOURCE)
    if ownership_evidence is not None:
        ownership_evidence.write_text(json.dumps(ownership, indent=2, sort_keys=True) + '\n')
    counts['output_ownership_cases'] = ownership['total']
    delivery = evaluate_delivery()
    counts['delivery_preflight_cases'] = delivery['total']
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FullReportTests)
    result = unittest.TextTestRunner(verbosity=1, stream=sys.stderr).run(suite)
    if not result.wasSuccessful():
        raise AssertionError('whole-report critical eval failed')
    counts['whole_report_tests'] = result.testsRun
    print(json.dumps({'status': 'PASS', 'threshold': 'all critical scenarios pass (100%)',
                      'scenarios': counts, 'total': sum(counts.values()), 'failed': 0,
                      'wall_seconds': round(time.perf_counter() - started, 6), 'seed': 20261105,
                      'network_calls': 0, 'returns_computed': False,
                      'policy_mutations': {key: value for key, value in policy.items() if key != 'cases'},
                      'exact_arithmetic': exactness,
                      'output_ownership': {key: value for key, value in ownership.items() if key != 'cases'}}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy-evidence', type=Path, help='Optional local JSON file for every policy-mutation case')
    parser.add_argument('--ownership-evidence', type=Path, help='Optional local JSON file for caller-output mutation cases')
    args = parser.parse_args()
    run(args.policy_evidence, args.ownership_evidence)
