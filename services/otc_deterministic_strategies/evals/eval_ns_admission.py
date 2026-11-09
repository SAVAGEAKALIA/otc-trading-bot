"""Exact-time regression with an isolated old-floor mutant, no external access."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import time
import types
import unittest
from unittest.mock import patch

from .. import policy
from ..tests import test_policy

METHODS = ('test_holding_bounds_preserve_exact_nanoseconds_for_both_fixed_policies',
           'test_closed_candle_staleness_uses_exact_derived_broker_nanoseconds',
           'test_purchase_deadline_one_nanosecond_before_and_at_cutoff',
           'test_exact_signed_broker_clock_offsets_preserve_one_nanosecond_limit')


def suite():
    return unittest.TestSuite(test_policy.PolicyTests(name) for name in METHODS)


def run(output):
    started = time.perf_counter()
    actual = unittest.TextTestRunner(stream=io.StringIO()).run(suite())
    path = Path(policy.__file__)
    original = path.read_text()
    expression = 'broker_now_ns = quote.broker_at_receipt_ms * 1000000 + decision_ns - quote.received_ns'
    if original.count(expression) != 1:
        raise ValueError('Precise derived-broker-time expression changed')
    floored = 'broker_now_ns = quote.broker_at_receipt_ms * 1000000 + ((decision_ns - quote.received_ns) // 1000000) * 1000000'
    mutant_source = original.replace(expression, floored)
    mutant = types.ModuleType(policy.__package__ + '.policy_ns_floor_mutant')
    mutant.__package__ = policy.__package__
    exec(compile(mutant_source, '<isolated-broker-ns-floor-mutant>', 'exec'), mutant.__dict__)
    with patch.object(test_policy, 'decide', mutant.decide):
        mutant_result = unittest.TextTestRunner(stream=io.StringIO()).run(suite())
    clock_expression = 'abs(broker_at_receipt_ms * 1000000 - received_ns) <= 15000000000'
    if original.count(clock_expression) != 1:
        raise ValueError('Precise broker-offset expression changed')
    old_clock = 'abs(broker_at_receipt_ms - received_ns // 1000000) <= 15000'
    clock_mutant = types.ModuleType(policy.__package__ + '.policy_offset_floor_mutant')
    clock_mutant.__package__ = policy.__package__
    exec(compile(original.replace(clock_expression, old_clock),
                 '<isolated-clock-offset-floor-mutant>', 'exec'), clock_mutant.__dict__)
    with patch.object(test_policy, 'decide', clock_mutant.decide), patch.object(test_policy, 'clock_valid', clock_mutant.clock_valid):
        clock_mutant_result = unittest.TextTestRunner(stream=io.StringIO()).run(suite())
    report = {'schema': 'otc_existing_strategy_exact_ns_eval_v1',
              'pass_threshold': 1.0, 'passed': actual.wasSuccessful() and
               not mutant_result.wasSuccessful() and bool(mutant_result.failures) and not mutant_result.errors and
               not clock_mutant_result.wasSuccessful() and bool(clock_mutant_result.failures) and not clock_mutant_result.errors,
              'real_regressions_passed': actual.wasSuccessful(), 'real_tests': actual.testsRun,
              'real_errors': len(actual.errors), 'real_failures': len(actual.failures),
              'old_floor_mutant_killed': not mutant_result.wasSuccessful(),
              'mutant_failures': len(mutant_result.failures), 'mutant_errors': len(mutant_result.errors),
              'mutant_failure_tests': [str(item[0]) for item in mutant_result.failures],
              'old_clock_offset_floor_mutant_killed': not clock_mutant_result.wasSuccessful(),
              'clock_offset_mutant_failures': len(clock_mutant_result.failures),
              'clock_offset_mutant_errors': len(clock_mutant_result.errors),
              'clock_offset_mutant_failure_tests': [str(item[0]) for item in clock_mutant_result.failures],
              'methods': list(METHODS), 'clock_domain': 'exact derived integer broker nanoseconds',
              'frozen_holding_bounds_ns': [90000000000, 150000000000],
              'holding_test_cases_per_policy': [89999999999, 90000000000, 150000000000, 150000000001],
              'signed_broker_clock_offsets_ns': [15000000000, 15000000001, -15000000000, -15000000001],
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
    args = parser.parse_args()
    return 0 if run(args.output)['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
