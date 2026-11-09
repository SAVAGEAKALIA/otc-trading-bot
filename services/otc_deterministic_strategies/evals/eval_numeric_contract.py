"""Seeded numeric stress and isolated exception-contract mutants, no external access."""
from __future__ import annotations

import argparse
import ast
from dataclasses import replace
import hashlib
import io
import json
import math
from pathlib import Path
import random
import time
import types
import unittest
from unittest.mock import patch

from .. import policy
from ..contracts import InvalidInput, POLICIES
from ..tests import test_numeric_contract
from ..tests.test_candle_identity import positive_inputs

OLD_POLICY_SHA256 = 'd0f55438d66e089950e140b0bb6ec45240cb6d89904d52d4d0117565c8d81ca2'
OLD_CONTRACTS_SHA256 = '0224d2ca32e8235aa216f43d83f24a6a75a206d8cbe4e3b7b748cac47e9c9ed1'
METHODS = tuple(name for name in sorted(dir(test_numeric_contract.NumericContractTests)) if name.startswith('test_'))


def suite():
    return unittest.TestSuite(test_numeric_contract.NumericContractTests(name) for name in METHODS)


def evidence(result):
    return {'tests': result.testsRun, 'passed': result.wasSuccessful(),
            'failures': len(result.failures), 'errors': len(result.errors),
            'failure_tests': [str(item[0]) for item in result.failures]}


def isolated_function(source, name):
    node = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {'math': math, 'json': json, 'InvalidInput': InvalidInput}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<isolated-old-' + name + '>', 'exec'), namespace)
    return namespace[name]


def run(output, repetitions=2000):
    started = time.perf_counter()
    runner = lambda: unittest.TextTestRunner(stream=io.StringIO()).run(suite())
    actual = runner()
    base = Path(policy.__file__).resolve().parent
    old_policy = (base / 'evidence/v4-before-numeric-repair-policy.py').read_bytes()
    old_contracts = (base / 'evidence/v4-before-numeric-repair-contracts.py').read_bytes()
    assert hashlib.sha256(old_policy).hexdigest() == OLD_POLICY_SHA256
    assert hashlib.sha256(old_contracts).hexdigest() == OLD_CONTRACTS_SHA256
    old_number = isolated_function(old_contracts.decode(), 'number')
    with patch.object(policy, 'number', old_number), patch.object(test_numeric_contract, 'number', old_number):
        number_mutant = runner()
    current = Path(policy.__file__).read_text()
    protected = ("    try:\n"
                 "        direction, reason, score = mhi_rule(prefix) if policy == POLICIES[0] else exhaustion_rule(prefix)\n"
                 "    except ArithmeticError as error:\n"
                 "        raise InvalidInput('indicator arithmetic exceeds the supported numeric range') from error\n")
    assert current.count(protected) == 1
    unprotected = "    direction, reason, score = mhi_rule(prefix) if policy == POLICIES[0] else exhaustion_rule(prefix)\n"
    module = types.ModuleType(policy.__package__ + '.indicator_overflow_mutant')
    module.__package__ = policy.__package__
    exec(compile(current.replace(protected, unprotected), '<isolated-indicator-overflow-mutant>', 'exec'), module.__dict__)
    with patch.object(test_numeric_contract, 'decide', module.decide):
        indicator_mutant = runner()
    old_canonical = isolated_function(old_policy.decode(), 'canonical')
    with patch.object(policy, 'canonical', old_canonical), patch.object(test_numeric_contract, 'canonical', old_canonical):
        encoding_mutant = runner()
    generator = random.Random(20261111)
    counts = {'huge_signed_number_checks': 0, 'huge_integer_field_checks': 0,
              'finite_ohlc_scale_checks': 0, 'normal_range_repeat_checks': 0}
    typed_stress_rejections = 0
    failures = []
    def reject(call, label):
        nonlocal typed_stress_rejections
        try:
            call()
        except InvalidInput:
            typed_stress_rejections += 1
        except Exception as error:
            failures.append(label + '/escaping-' + type(error).__name__)
        else:
            failures.append(label + '/huge-integer-admitted')
    for repetition in range(repetitions):
        huge = 10 ** generator.randrange(400, 1201)
        for sign in (-1, 1):
            reject(lambda: policy.number(sign * huge, 'seeded huge integer'), f'{repetition}/number/{sign}')
            counts['huge_signed_number_checks'] += 1
        for name in POLICIES:
            decision_ns, offer, quote, rows = positive_inputs(name)
            original = policy.decide(name, quote.asset, decision_ns, offer, quote, rows)
            if original != policy.decide(name, quote.asset, decision_ns, offer, quote, rows):
                failures.append(f'{repetition}/{name}/normal-repeat-changed')
            counts['normal_range_repeat_checks'] += 1
            changes = [(replace(offer, payout=huge), quote, rows),
                       (offer, replace(quote, price=huge), rows)]
            chosen = generator.randrange(len(rows))
            for field in ('open', 'high', 'low', 'close'):
                changes.append((offer, quote, rows[:chosen] +
                                (replace(rows[chosen], **{field: huge}),) + rows[chosen + 1:]))
            for index, (changed_offer, changed_quote, changed_rows) in enumerate(changes):
                reject(lambda: policy.decide(name, quote.asset, decision_ns, changed_offer, changed_quote, changed_rows),
                       f'{repetition}/{name}/field/{index}')
                counts['huge_integer_field_checks'] += 1
        for put in (False, True):
            scale = 10.0 ** generator.uniform(-306.0, 306.0)
            data = test_numeric_contract.exhaustion_inputs(put, scale)
            assert all(math.isfinite(getattr(row, field)) and getattr(row, field) > 0
                       for row in data[-1] for field in ('open', 'high', 'low', 'close'))
            try:
                value = policy.decide(POLICIES[1], data[2].asset, *data)
            except InvalidInput:
                typed_stress_rejections += 1
            except Exception as error:
                failures.append(f'{repetition}/finite-scale/{put}/escaping-{type(error).__name__}')
            else:
                if value.direction not in (None, 'call', 'put') or value.capital_permission:
                    failures.append(f'{repetition}/finite-scale/{put}/invalid-signal-contract')
            counts['finite_ohlc_scale_checks'] += 1
    killed = lambda value: not value.wasSuccessful() and bool(value.failures) and not value.errors
    report = {'schema': 'otc_existing_strategy_numeric_contract_eval_v1',
              'pass_threshold': 1.0,
              'passed': actual.wasSuccessful() and not failures and all(killed(value) for value in
                        (number_mutant, indicator_mutant, encoding_mutant)),
              'regression': evidence(actual), 'old_number_mutant': evidence(number_mutant),
              'unprotected_indicator_mutant': evidence(indicator_mutant),
              'unprotected_encoding_mutant': evidence(encoding_mutant),
              'old_number_mutant_killed': killed(number_mutant),
              'unprotected_indicator_mutant_killed': killed(indicator_mutant),
              'unprotected_encoding_mutant_killed': killed(encoding_mutant),
              'seed': 20261111, 'repetitions': repetitions, 'checks': sum(counts.values()),
              'counts': counts, 'typed_stress_rejections': typed_stress_rejections, 'failures': failures,
              'scale_exponent_range': [-306.0, 306.0], 'huge_integer_digit_exponent_range': [400, 1200],
              'current_policy_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'current_contracts_sha256': hashlib.sha256((base / 'contracts.py').read_bytes()).hexdigest(),
              'policy_thresholds_changed': False, 'trial_slots_changed': False,
              'broker_calls': 0, 'orders': 0, 'future_live_data_used': False,
              'synthetic_numeric_stress_is_not_economic_evidence': True,
              'wall_seconds': time.perf_counter() - started}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as target:
        json.dump(report, target, indent=2)
        target.write('\n')
    print(json.dumps(report, sort_keys=True))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--repetitions', type=int, default=2000)
    args = parser.parse_args()
    if args.repetitions < 2000:
        raise ValueError('Numeric stress eval requires at least2000 frozen repetitions')
    return 0 if run(args.output, args.repetitions)['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
