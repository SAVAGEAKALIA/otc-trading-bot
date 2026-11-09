"""Read-only Git validation of proposed text changes, including new files."""
import difflib
from pathlib import Path
import re
import subprocess
import tempfile


def additions_patch(files: dict[str, bytes]) -> bytes:
    parts = []
    for name, raw in sorted(files.items()):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', name) or any(
                part in ('.', '..') for part in name.split('/')):
            raise ValueError('safe relative source path required')
        parts.extend([f'diff --git a/{name} b/{name}\n', 'new file mode 100644\n'])
        for line in difflib.unified_diff([], raw.decode('utf-8').splitlines(keepends=True),
                                         fromfile='/dev/null', tofile='b/' + name):
            parts.append(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n')
    return ''.join(parts).encode('utf-8')


def check_patch(patch: bytes, baseline: Path | None = None) -> None:
    """Reject application and whitespace errors without changing files or an index."""
    with tempfile.TemporaryDirectory(prefix='d3-delivery-') as directory:
        temporary = Path(directory)
        patch_file = temporary / 'proposed.patch'
        patch_file.write_bytes(patch)
        if baseline is None:
            baseline = temporary / 'baseline'
            baseline.mkdir()
        result = subprocess.run(['git', 'apply', '--check', '--whitespace=error-all', str(patch_file)],
                                cwd=baseline, capture_output=True, timeout=15)
        if result.returncode:
            diagnostic = result.stderr.decode('utf-8', errors='replace')
            mentioned = {int(number) for number in re.findall(r':(\d+):', diagnostic)}
            current, affected = '', set()
            for number, line in enumerate(patch.decode('utf-8').splitlines(), 1):
                if line.startswith('+++ b/'):
                    current = line[6:]
                if number in mentioned and current:
                    affected.add(current)
            sources = '\nAffected source: ' + ', '.join(sorted(affected)) if affected else ''
            raise ValueError('proposed delivery rejected:\n' + diagnostic + sources)
