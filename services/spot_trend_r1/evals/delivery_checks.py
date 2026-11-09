"""Generated delivery cases use independently declared Git whitespace outcomes."""
import difflib
import hashlib
import json
from pathlib import Path
import random
import sys
import tempfile

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE))
from delivery import additions_patch, check_patch


def evaluate(seed=20261107, samples=128):
    rng = random.Random(seed)
    cases = []
    for case in range(samples):
        kind = ('valid', 'extra_eof_blank', 'trailing_space', 'interior_blank')[case % 4]
        existing = bool((case // 4) % 2)
        name = rng.choice(('source.py', 'nested/data.json', 'deep/nested/notes.md'))
        first = f'value = {rng.randrange(100000)}\n'
        proposed = {'valid': first, 'extra_eof_blank': first + '\n' * rng.randint(1, 3),
                    'trailing_space': first.rstrip('\n') + ' ' * rng.randint(1, 3) + '\n',
                    'interior_blank': first + '\n' + 'note = "café"\n'}[kind]
        expected = kind in ('valid', 'interior_blank')
        with tempfile.TemporaryDirectory(prefix='d3-delivery-eval-') as directory:
            base = Path(directory)
            if existing:
                original = 'previous = 1\n'
                source = base / name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text(original)
                patch = (f'diff --git a/{name} b/{name}\n' + ''.join(difflib.unified_diff(
                    original.splitlines(keepends=True), proposed.splitlines(keepends=True),
                    fromfile='a/' + name, tofile='b/' + name))).encode()
            else:
                patch = additions_patch({name: proposed.encode()})
            try:
                check_patch(patch, base)
                accepted, error = True, ''
            except ValueError as exc:
                accepted, error = False, str(exc)
            cases.append({'case': case, 'kind': kind, 'existing_file': existing, 'path': name,
                          'expected_accept': expected, 'actual_accept': accepted,
                          'passed': accepted == expected,
                          'error_sha256': hashlib.sha256(error.encode()).hexdigest()})
            if accepted != expected:
                raise AssertionError('delivery preflight mismatch: ' + str(cases[-1]))
    files = {path.relative_to(SERVICE).as_posix(): path.read_bytes()
             for path in SERVICE.rglob('*') if path.is_file()
             and path.suffix in ('.py', '.json', '.md') and '__pycache__' not in path.parts}
    assert 'evals/test_full_plan.py' in files
    check_patch(additions_patch(files))
    cases.append({'case': samples, 'kind': 'complete_service_source_sweep',
                  'expected_accept': True, 'actual_accept': True, 'passed': True,
                  'source_files_checked': len(files)})
    return {'status': 'PASS', 'threshold': 'all critical scenarios pass (100%)',
            'seed': seed, 'total': len(cases), 'failed': 0, 'cases': cases,
            'case_results_sha256': hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest()}
