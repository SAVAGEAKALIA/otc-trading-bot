"""Generated same-module caller mutation checks for fresh report ownership."""
from collections import Counter
from pathlib import Path
import random
import sys

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE))
import plan


def mutable_nodes(value, path=(), seen=None):
    if type(value) not in (dict, list):
        return
    if seen is None:
        seen = set()
    if id(value) in seen:
        return
    seen.add(id(value))
    yield path, value
    if type(value) is dict:
        for key in sorted(value):
            yield from mutable_nodes(value[key], path + (key,), seen)
    else:
        for index, child in enumerate(value):
            yield from mutable_nodes(child, path + (index,), seen)


def at_path(value, path):
    for key in path:
        value = value[key]
    return value


def annotate(node, case, rng):
    note = {'comments': [f'caller note {case}', {'tags': ['local', 'review']}]}
    if type(node) is dict:
        action = rng.choice(('annotate_dict', 'clear_dict', 'overwrite_dict_field'))
        if action == 'clear_dict':
            node.clear()
        elif action == 'overwrite_dict_field' and node:
            node[sorted(node)[0]] = {'caller_replacement': [str(case)]}
        node[f'__caller_annotation_{case}__'] = note
    else:
        action = rng.choice(('append_list', 'clear_list', 'remove_list_item'))
        if action == 'clear_list':
            node.clear()
        elif action == 'remove_list_item' and node:
            node.pop(rng.randrange(len(node)))
        node.append(note)
    note['comments'][1]['tags'].append(f'edited-{case}')
    return action


def evaluate(source_dir, seed=20261105, seeded_cases=32):
    rng = random.Random(seed)
    module = plan
    paths = [Path(source_dir) / name for name in plan.SOURCE_HASHES]
    paths.append(SERVICE / 'contracts' / 'protocol.json')
    input_bytes = {path: path.read_bytes() for path in paths}
    first = plan.run(Path(source_dir))
    expected = plan.canonical(first)
    reports = [first]
    # Keep the actual objects alive, including children removed by a caller,
    # so Python cannot recycle ids and create false alias reports.
    owned_objects = {id(node): node for _, node in mutable_nodes(first)}
    original_mutable_count = len(owned_objects)
    requirements = first['requirements']
    purposes = sorted(requirements)
    forced = [('requirements_root', ('requirements',))]
    for purpose in purposes:
        forced.append(('purpose_list', ('requirements', purpose)))
        if requirements[purpose]:
            row = requirements[purpose][0]
            if type(row.get('window')) is dict:
                forced.append(('nested_window', ('requirements', purpose, 0, 'window')))
            if type(row.get('blockers')) is list:
                forced.append(('nested_blocker_list', ('requirements', purpose, 0, 'blockers')))
    cases = []
    plan_calls = 1
    for case in range(len(forced) + seeded_cases):
        if case < len(forced):
            category, path = forced[case]
            prior_index = len(reports) - 1
            earlier = reports[prior_index]
            node = at_path(earlier, path)
        else:
            category = 'seeded_retained_report_mutation'
            prior_index = rng.randrange(len(reports))
            earlier = reports[prior_index]
            candidates = list(mutable_nodes(earlier['requirements'], ('requirements',)))
            path, node = rng.choice(candidates)
        before = plan.canonical(earlier)
        action = annotate(node, case, rng)
        if plan.canonical(earlier) == before:
            raise AssertionError('ownership probe did not mutate the caller report')
        owned_objects.update((id(child), child) for _, child in mutable_nodes(earlier))
        fresh = plan.run(Path(source_dir))
        plan_calls += 1
        unchanged = plan.canonical(fresh) == expected
        fresh_objects = {id(child): child for _, child in mutable_nodes(fresh)}
        aliases = set(fresh_objects) & set(owned_objects)
        passed = unchanged and not aliases and plan is module
        cases.append({'case': case, 'category': category, 'prior_report_index': prior_index,
                      'path': list(path), 'target_type': type(node).__name__, 'action': action,
                      'fresh_output_byte_identical': unchanged, 'shared_mutable_objects': len(aliases),
                      'same_loaded_module': plan is module, 'passed': passed})
        if not passed:
            raise AssertionError('caller output mutation contaminated a later plan: ' + str(cases[-1]))
        reports.append(fresh)
        owned_objects.update(fresh_objects)
    unchanged_inputs = all(path.read_bytes() == raw for path, raw in input_bytes.items())
    if not unchanged_inputs:
        raise AssertionError('ownership eval changed source/contract bytes')
    return {'status': 'PASS', 'threshold': 'all critical scenarios pass (100%)',
            'seed': seed, 'seeded_cases': seeded_cases, 'total': len(cases), 'failed': 0,
            'plan_calls_in_same_loaded_module': plan_calls, 'module_reloads': 0,
            'source_and_contract_bytes_unchanged': unchanged_inputs,
            'baseline_sha256': plan.digest(expected), 'baseline_mutable_containers': original_mutable_count,
            'purpose_groups_exercised': purposes,
            'cases_by_category': dict(sorted(Counter(case['category'] for case in cases).items())),
            'actions': dict(sorted(Counter(case['action'] for case in cases).items())),
            'shared_mutable_objects': 0, 'case_results_sha256': plan.digest(plan.canonical(cases)),
            'cases': cases}
