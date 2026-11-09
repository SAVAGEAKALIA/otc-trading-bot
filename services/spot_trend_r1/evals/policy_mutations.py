"""Generated semantic attacks; expectations come from the supported input tree.

No expected result uses the planner's contract hash or selective field checks.
Every single-field policy mutation is unsupported; only JSON layout may vary.
"""
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE))
import plan


def walk(value, path=()):
    yield path, value
    if type(value) is dict:
        for key in sorted(value):
            yield from walk(value[key], path + (key,))
    elif type(value) is list:
        for index, child in enumerate(value):
            yield from walk(child, path + (index,))


def altered(contract, path, replacement):
    if not path:
        return replacement
    result = deepcopy(contract)
    node = result
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = replacement
    return result


def changed_leaf(value):
    if type(value) is str:
        return value + ' ALTERED'
    if type(value) is bool:
        return not value
    if type(value) is int:
        return value + 1
    return 'invented fact'


def evaluate(source_dir, seed=20261105):
    raw = (SERVICE / 'contracts' / 'protocol.json').read_bytes()
    contract = plan.read_json(raw)
    tree = list(walk(contract))
    leaves = [(path, value) for path, value in tree if type(value) not in (dict, list)]
    objects = [(path, value) for path, value in tree if type(value) is dict]
    arrays = [(path, value) for path, value in tree if type(value) is list]
    rng = random.Random(seed)
    cases, cli_inputs = [], []

    def reject(category, path, replacement, label=None):
        candidate = altered(contract, path, replacement)
        try:
            plan.validate_contract(candidate)
        except ValueError:
            passed = True
        else:
            passed = False
        cases.append({'category': category, 'path': list(path), 'label': label or category,
                      'replacement_type': type(replacement).__name__, 'expected': 'reject', 'passed': passed})
        return candidate

    for path, value in leaves:
        reject('every_leaf_policy_change', path, changed_leaf(value))
        if type(value) is int:
            alternatives = (float(value), str(value), True, False, None, value - 1, -value, [], {})
        elif type(value) is bool:
            alternatives = (int(value), str(value).lower(), None, [], {})
        elif value is None:
            alternatives = (0, False, 'null', [], {})
        else:
            alternatives = ('', 0, True, None, [value], {'value': value})
        for alternative in alternatives:
            reject('leaf_type_and_numeric_substitution', path, alternative)

    for path, value in objects:
        for key, extra in (('fee_rate', 0), ('live_trading_authorized', True),
                           ('unregistered_policy', {'nested': {'live_trading_authorized': True}})):
            candidate = reject('top_and_nested_addition', path, dict(value, **{key: extra}), key)
            if key == 'live_trading_authorized':
                cli_inputs.append(('nested_addition:' + str(path), json.dumps(candidate).encode()))
        for key in sorted(value):
            removed = deepcopy(value)
            removed.pop(key)
            reject('every_object_field_omission', path, removed, key)
            renamed = deepcopy(value)
            renamed['unregistered_' + key] = renamed.pop(key)
            reject('every_object_field_rename', path, renamed, key)
        for alternative in (None, [], list(value.items()), {}):
            reject('object_type_substitution', path, alternative)

    for path, value in arrays:
        alternatives = ([], value[:-1], value + value[:1],
                        value + [{'live_trading_authorized': True}], {'items': value}, None)
        for alternative in alternatives:
            reject('array_shape_and_type_change', path, alternative)
        if value != list(reversed(value)):
            reject('array_order_change', path, list(reversed(value)))

    for case in range(128):
        selection = rng.sample(leaves, rng.randint(2, 7))
        candidate = deepcopy(contract)
        for path, value in selection:
            candidate = altered(candidate, path, changed_leaf(value))
        object_path, _ = rng.choice(objects)
        node = candidate
        for key in object_path:
            node = node[key]
        # An ancestor might have been changed by a selected leaf only, so all
        # object shapes are still present; combined attacks include additions.
        node['invented_policy'] = {'fee_rate': 0, 'live_trading_authorized': True}
        reject('seeded_combined_policy_attack', (), candidate, str(case))

    # Key order, indentation and JSON escapes are syntax, not a policy change.
    def reordered(value):
        if type(value) is dict:
            keys = list(value)
            rng.shuffle(keys)
            return {key: reordered(value[key]) for key in keys}
        if type(value) is list:
            return [reordered(child) for child in value]
        return value

    for case in range(32):
        formatted = json.dumps(reordered(contract), indent=rng.choice((None, 1, 2, 4)),
                               ensure_ascii=bool(case % 2)).encode()
        candidate = plan.read_json(formatted)
        try:
            plan.validate_contract(candidate)
        except ValueError:
            passed = False
        else:
            passed = True
        cases.append({'category': 'semantic_layout_equivalent', 'path': [], 'label': str(case),
                      'expected': 'accept', 'passed': passed,
                      'raw_bytes_differ': formatted != raw})

    attacks = [
        (('allocation', 'transfers_between_components'), 'allowed'),
        (('execution', 'retry_policy'), 'retry daily, including hold days'),
        (('terminal', 'closing_valuation'), 'midnight before terminal execution'),
        (('accounting', 'b0'), 'USDT=USD=1'),
        (('fee_rate',), 0),
        (('live_trading_authorized',), True),
    ]
    combined = deepcopy(contract)
    for path, value in attacks:
        candidate = altered(contract, path, value)
        cli_inputs.append(('reported_attack:' + str(path), json.dumps(candidate).encode()))
        combined = altered(combined, path, value)
    cli_inputs.append(('all_reported_attacks_combined', json.dumps(combined).encode()))
    for path, value in leaves:
        if type(value) in (int, bool):
            substitute = float(value) if type(value) is int else int(value)
            candidate = altered(contract, path, substitute)
            cli_inputs.append(('numeric_type:' + str(path), json.dumps(candidate).encode()))
    cli_inputs.extend([
        ('root_null', b'null'), ('root_array', b'[]'),
        ('duplicate_key', b'{"status":"DESCRIPTIVE_ONLY","status":"DESCRIPTIVE_ONLY"}'),
        ('nonfinite', b'{"field":NaN}'),
        ('exponent_overflow', b'{"field":1e10000}'),
        ('excessive_nesting', b'[' * 1500 + b'0' + b']' * 1500),
    ])
    with tempfile.TemporaryDirectory() as directory:
        contract_path = Path(directory) / 'mutated-contract.json'
        command = [sys.executable, str(SERVICE / 'plan.py'), '--source-dir', str(Path(source_dir).resolve()),
                   '--contract', str(contract_path)]
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        for label, candidate_raw in cli_inputs:
            contract_path.write_bytes(candidate_raw)
            process = subprocess.run(command, capture_output=True, check=False, cwd=directory,
                                     env=environment, timeout=15)
            passed = (process.returncode == 2 and process.stdout == b''
                      and process.stderr.startswith(b'INPUT_REJECTED:'))
            cases.append({'category': 'actual_cli_rejection', 'path': [], 'label': label,
                          'expected': 'exit_2_INPUT_REJECTED_empty_stdout', 'passed': passed,
                          'exit_code': process.returncode, 'stdout_bytes': len(process.stdout),
                          'input_rejected': process.stderr.startswith(b'INPUT_REJECTED:')})

    failures = [case for case in cases if not case['passed']]
    report = {'status': 'FAIL' if failures else 'PASS', 'threshold': 'all critical scenarios pass (100%)',
              'seed': seed, 'total': len(cases), 'failed': len(failures),
              'cases_by_category': dict(sorted(Counter(case['category'] for case in cases).items())),
              'coverage': {'contract_leaves': len(leaves), 'contract_objects': len(objects),
                           'contract_arrays': len(arrays), 'every_leaf_mutated': True,
                           'every_object_addition_omission_and_rename_tested': True,
                           'every_array_shape_tested': True},
              'case_results_sha256': plan.digest(plan.canonical(cases)), 'cases': cases}
    if failures:
        raise AssertionError('Critical policy scenarios failed: ' + json.dumps(failures))
    return report
