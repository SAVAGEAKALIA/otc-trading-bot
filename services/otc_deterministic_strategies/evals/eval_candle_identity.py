"""Order/distant-identity regressions and isolated identity-selection mutants."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import io
from itertools import permutations
import json
from pathlib import Path
import random
import time
import types
import unittest
from unittest.mock import patch

from .. import policy
from ..contracts import InvalidInput, POLICIES
from ..tests import test_candle_identity

OLD_POLICY_SHA256 = '39e231b7dc95790458d4cbe94e298f3347e46741db0152df19e9b63598623e71'
METHODS = tuple(name for name in sorted(dir(test_candle_identity.CandleIdentityTests))
                if name.startswith('test_'))


def suite():
    return unittest.TestSuite(test_candle_identity.CandleIdentityTests(name) for name in METHODS)


def isolated_module(source, name):
    module = types.ModuleType(policy.__package__ + '.' + name)
    module.__package__ = policy.__package__
    exec(compile(source, '<isolated-' + name + '>', 'exec'), module.__dict__)
    return module


def mutant_result(module):
    with patch.object(test_candle_identity, 'decide', module.decide):
        return unittest.TextTestRunner(stream=io.StringIO()).run(suite())


def result_evidence(result):
    return {'tests': result.testsRun, 'passed': result.wasSuccessful(),
            'failures': len(result.failures), 'errors': len(result.errors),
            'failure_tests': [str(item[0]) for item in result.failures]}


def run(output, repetitions=2000):
    started = time.perf_counter()
    actual = unittest.TextTestRunner(stream=io.StringIO()).run(suite())
    base = Path(policy.__file__).resolve().parent
    original = Path(policy.__file__).read_text()
    old_bytes = (base / 'evidence/policy-v3-before-identity-repair.py').read_bytes()
    if hashlib.sha256(old_bytes).hexdigest() != OLD_POLICY_SHA256:
        raise ValueError('Preserved v3 mutant source changed')
    old_result = mutant_result(isolated_module(old_bytes.decode(), 'latest_version_only_mutant'))
    identity_check = 'if prior_identity is not None and prior_identity != item:'
    if original.count(identity_check) != 1:
        raise ValueError('Causal finalized identity expression changed')
    narrowed_check = ('if prior_identity is not None and prior_identity != item and '
                      'item.start_ms >= broker_now_ns // 1000000 - 29 * 120000:')
    window_result = mutant_result(isolated_module(original.replace(identity_check, narrowed_check),
                                                  'feature_window_identity_mutant'))
    generator = random.Random(20261110)
    counts = {'permutation_conflict_checks': 0, 'distant_permutation_conflict_checks': 0,
              'distinct_receipt_duplicate_invariance_checks': 0}
    failures = []
    for repetition in range(repetitions):
        for name in POLICIES:
            data = test_candle_identity.positive_inputs(name, offset_bars=80)
            decision_ns, offer, quote, rows = data
            chosen = generator.randrange(len(rows))
            a = rows[chosen]
            for distant in (False, True):
                if distant:
                    start_ms = generator.randrange(1, 51) * test_candle_identity.BAR_MS
                    a = replace(rows[chosen], start_ms=start_ms,
                                received_ns=(start_ms + test_candle_identity.BAR_MS) * test_candle_identity.MS_NS,
                                broker_at_receipt_ms=start_ms + test_candle_identity.BAR_MS)
                b = replace(a, open=a.open + generator.uniform(0.005, 0.05))
                c = replace(a, received_ns=a.received_ns + generator.choice((1, 1000, 1000000)))
                at_ns = max(decision_ns, c.received_ns)
                unchanged = list(rows if distant else rows[:chosen] + rows[chosen + 1:])
                generator.shuffle(unchanged)
                for index, order in enumerate(permutations((a, b, c))):
                    split = generator.randrange(len(unchanged) + 1)
                    admitted = tuple(unchanged[:split]) + order + tuple(unchanged[split:])
                    try:
                        policy.decide(name, quote.asset, at_ns, offer, quote, admitted)
                    except InvalidInput as error:
                        if 'conflicting candle version' not in str(error):
                            failures.append(f'{name}/{repetition}/{distant}/{index}/unexpected-invalid-input')
                    else:
                        failures.append(f'{name}/{repetition}/{distant}/{index}/conflict-admitted')
                    key = 'distant_permutation_conflict_checks' if distant else 'permutation_conflict_checks'
                    counts[key] += 1
            a = rows[chosen]
            prior = replace(a, received_ns=a.received_ns - 1, open=a.open + 0.01)
            expected = policy.decide(name, quote.asset, decision_ns, offer, quote, rows)
            duplicated = list(rows) + [prior, a]
            generator.shuffle(duplicated)
            if expected != policy.decide(name, quote.asset, decision_ns, offer, quote, duplicated):
                failures.append(f'{name}/{repetition}/distinct-receipt-duplicate-evidence-changed')
            counts['distinct_receipt_duplicate_invariance_checks'] += 1
    killed = lambda value: not value.wasSuccessful() and bool(value.failures) and not value.errors
    report = {'schema': 'otc_existing_strategy_candle_identity_eval_v1',
              'pass_threshold': 1.0,
              'passed': actual.wasSuccessful() and not failures and killed(old_result) and killed(window_result),
              'regression': result_evidence(actual),
              'old_latest_version_only_mutant': result_evidence(old_result),
              'feature_window_identity_mutant': result_evidence(window_result),
              'old_latest_version_only_mutant_killed': killed(old_result),
              'feature_window_identity_mutant_killed': killed(window_result),
              'old_policy_sha256': OLD_POLICY_SHA256,
              'current_policy_sha256': hashlib.sha256(original.encode()).hexdigest(),
              'seed': 20261110, 'repetitions': repetitions, 'counts': counts,
              'checks': sum(counts.values()), 'failures': failures,
              'identity_domain': 'all causally received finalized records for the selected asset, before eligibility and latest-version selection',
              'policy_thresholds_changed': False, 'trial_slots_changed': False,
              'broker_calls': 0, 'orders': 0, 'future_live_data_used': False,
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
        raise ValueError('Identity eval requires at least2000 frozen repetitions')
    return 0 if run(args.output, args.repetitions)['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
