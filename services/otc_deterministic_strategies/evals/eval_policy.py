"""Compare frozen rules against archived classes, then perturb future data."""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from ..contracts import InvalidInput
from ..policy import (decide, exhaustion_rule, legacy_adx, legacy_bb_position,
                      legacy_rsi, legacy_stochastic, mhi_rule)
from ..tests.support import ASSET, DECISION_MS, DECISION_NS, candles, inputs


@dataclass
class LegacyResult:
    score: float
    direction: str
    confidence: float
    reasons: list
    warnings: list
    should_trade: bool
    confluence: int = 0


class LegacyBase:
    def __init__(self, name):
        self.name = name


def pinned_source(repository, path, registration):
    code = subprocess.check_output(['git', '-C', str(repository), 'show',
                                    registration['source_tag'] + ':' + path])
    if hashlib.sha256(code).hexdigest() != registration['source_sha256'][path]:
        raise ValueError('Archived source changed')
    return code.decode()


def legacy_references(repository, registration):
    """Execute only known local pure class/function ASTs, never module imports."""
    namespace = {'BaseStrategy': LegacyBase, 'StrategyResult': LegacyResult,
                 'get_completed_candles': lambda rows, min_required: rows if len(rows) >= min_required else [],
                 'Dict': Dict, 'Any': Any, 'List': List, 'Optional': Optional,
                 'Tuple': Tuple, 'math': math}
    for name, filename in [('MHIStrategy', 'mhi_strategy.py'),
                           ('ExhaustionFadeStrategy', 'exhaustion_fade.py')]:
        path = 'trading_platform/strategies/otc/implementations/' + filename
        tree = ast.parse(pinned_source(repository, path, registration))
        node = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == name)
        module = ast.Module(body=[node], type_ignores=[])
        exec(compile(module, '<pinned-local-' + name + '>', 'exec'), namespace)
    path = 'trading_platform/legacy/iqoption_bot/analytics.py'
    tree = ast.parse(pinned_source(repository, path, registration))
    methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and
               node.name in ('_calculate_rsi', '_calculate_adx', '_calculate_bollinger', '_calculate_stochastic')]
    holder = ast.ClassDef(name='LegacyIndicators', bases=[], keywords=[], body=methods, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[holder], type_ignores=[]))
    exec(compile(module, '<pinned-local-indicators>', 'exec'), namespace)
    return namespace['MHIStrategy']('mhi'), namespace['ExhaustionFadeStrategy'](), namespace['LegacyIndicators']()


def run(repository, output, repetitions=2000):
    started = time.perf_counter()
    base = Path(__file__).resolve().parents[1]
    registration = json.loads((base / 'frozen_rules.json').read_text())
    mhi, exhaustion, indicators = legacy_references(repository, registration)
    randomizer = random.Random(20261109)
    counts = {'legacy_direction_checks': 0, 'legacy_indicator_checks': 0,
              'future_perturbation_checks': 0, 'negative_offer_checks': 0,
              'missing_contract_checks': 0, 'mhi_signals': 0, 'exhaustion_signals': 0}
    failures = []
    def check(condition, label):
        if not condition:
            failures.append(label)
    offer, quote, _ = inputs()
    for repetition in range(repetitions):
        closes = [100.0 + randomizer.gauss(0, 1) for _ in range(28)]
        closes.append(100.0 + randomizer.choice((-1, 1)) * randomizer.uniform(0, 4))
        prefix = candles(closes)
        prefix = [replace(item, open=item.close + randomizer.uniform(-0.35, 0.35),
                          high=item.close + 0.4, low=item.close - 0.4) for item in prefix]
        raw = [{'open': item.open, 'close': item.close, 'max': item.high, 'min': item.low}
               for item in prefix]
        highs = [item.high for item in prefix]
        lows = [item.low for item in prefix]
        legacy_rsi_value = indicators._calculate_rsi(closes)
        legacy_bb_upper, _, legacy_bb_lower = indicators._calculate_bollinger(closes)
        bb_position = 0.5 if legacy_bb_upper == legacy_bb_lower else (closes[-1] - legacy_bb_lower) / (legacy_bb_upper - legacy_bb_lower)
        stochastic, stochastic_d = indicators._calculate_stochastic(highs, lows, closes)
        legacy_adx_value = indicators._calculate_adx(highs, lows, closes)
        for current, reference, label in [(legacy_rsi(closes), legacy_rsi_value, 'RSI'),
                                           (legacy_bb_position(closes), bb_position, 'BB'),
                                           (legacy_stochastic(prefix), stochastic, 'stochastic'),
                                           (legacy_adx(prefix), legacy_adx_value, 'ADX')]:
            check(math.isclose(current, reference, rel_tol=1e-12, abs_tol=1e-12),
                  f'{label}-parity-{repetition}')
            counts['legacy_indicator_checks'] += 1
        kwargs = {'profile': 'reversal', 'indicators_2m': {'rsi': legacy_rsi_value,
                  'bb_position': bb_position, 'stoch_k': stochastic,
                  'stoch_d': stochastic_d, 'adx': legacy_adx_value}}
        for policy, reference_model, pure_rule in [('legacy_mhi3_causal', mhi, mhi_rule),
                                                 ('legacy_exhaustion_causal', exhaustion, exhaustion_rule)]:
            reference = reference_model.analyze(raw, **kwargs)
            current_direction, _, _ = pure_rule(prefix)
            reference_direction = reference.direction if reference.should_trade else None
            check(current_direction == reference_direction, f'{policy}-legacy-direction-{repetition}')
            counts['legacy_direction_checks'] += 1
            if current_direction:
                counts['mhi_signals' if policy == 'legacy_mhi3_causal' else 'exhaustion_signals'] += 1
            current = decide(policy, ASSET, DECISION_NS, offer, quote, prefix)
            future = replace(prefix[-1], start_ms=DECISION_MS, received_ns=DECISION_NS + 1,
                             open=math.nan, high=math.inf, low=-math.inf, close=math.nan)
            check(current == decide(policy, ASSET, DECISION_NS, offer, quote, prefix + [future]),
                  f'{policy}-future-invariance-{repetition}')
            counts['future_perturbation_checks'] += 1
            negative = replace(offer, active=False, status='unsupported_offer_state')
            check(not decide(policy, ASSET, DECISION_NS, negative, quote, prefix).should_trade,
                  f'{policy}-negative-offer-{repetition}')
            counts['negative_offer_checks'] += 1
            check(not decide(policy, ASSET, DECISION_NS, None, quote, prefix).should_trade,
                  f'{policy}-missing-contract-{repetition}')
            counts['missing_contract_checks'] += 1
    report = {'schema': 'otc_existing_policy_eval_v1', 'pass_threshold': 1.0,
              'passed': not failures, 'failures': failures, 'repetitions': repetitions,
              'seed': 20261109, 'counts': counts, 'wall_seconds': time.perf_counter() - started,
              'registration_sha256': registration['registration_sha256'],
              'legacy_source_commit': registration['source_commit'],
              'synthetic_signal_counts_are_not_economic_evidence': True,
              'future_live_data_used': False, 'broker_calls': 0, 'orders': 0}
    report['checks'] = sum(counts[name] for name in ('legacy_direction_checks',
        'legacy_indicator_checks', 'future_perturbation_checks', 'negative_offer_checks',
        'missing_contract_checks'))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as target:
        json.dump(report, target, indent=2)
        target.write('\n')
    print(json.dumps(report, sort_keys=True))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--repetitions', type=int, default=2000)
    args = parser.parse_args()
    if args.repetitions < 2000:
        raise ValueError('Periodic eval requires at least2000 frozen repetitions')
    return 0 if run(args.repository, args.output, args.repetitions)['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
