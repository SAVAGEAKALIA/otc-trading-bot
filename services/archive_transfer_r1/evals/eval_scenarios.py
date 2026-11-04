"""Offline generalization matrix; all scenarios must pass."""
import io
import json
from pathlib import Path
import random
import sys
import tempfile
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tests'))
from transfer import Downloader, Invalid
from test_transfer import Fake, URL

rng = random.Random(271828)
results = []
for index in range(12):
    with tempfile.TemporaryDirectory() as folder:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('random.data', rng.randbytes(rng.randrange(1, 2000)))
        data = stream.getvalue()
        fake = Fake(data)
        item = dict(url=URL, size=len(data))
        chunk = rng.choice([64, 127, 256, 1024, 4096])
        download = Downloader(folder, workers=rng.choice([1, 2, 4]), chunk_bytes=chunk,
                              opener=fake, sleeper=lambda _: None)
        outcome = download.archive(item)
        assert Path(outcome['local_file']).read_bytes() == data
        chunks = list(Path(folder).glob('*.chunks/*.bin'))
        damaged = rng.choice(chunks)
        damaged.write_bytes(b'x' * damaged.stat().st_size)
        fake.calls.clear()
        resumed = download.archive(item)
        assert Path(resumed['local_file']).read_bytes() == data
        assert len(fake.calls) == 2, 'probe plus exactly one damaged chunk'
        fake.tag = '"changed-version"'
        try:
            download.archive(item)
        except Invalid:
            pass
        else:
            raise AssertionError('remote identity drift accepted')
        results.append(dict(case=index, chunk_bytes=chunk, size=len(data), passed=True))
print(json.dumps(dict(threshold=1.0, evaluated=len(results), passed=True, scenarios=results)))
# Distinct-name and duplicate-name archives must both fail the single-member contract.
import warnings
for names in [('same', 'same'), ('a', 'b'), ('folder/',)]:
    with tempfile.TemporaryDirectory() as folder:
        stream = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(stream, 'w') as archive:
                for name in names:
                    archive.writestr(name, b'example')
        data = stream.getvalue()
        fake = Fake(data)
        downloader = Downloader(folder, opener=fake)
        try:
            downloader.archive(dict(url=URL, size=len(data)))
        except Invalid:
            pass
        else:
            raise AssertionError('invalid member structure accepted')
        assert not list(Path(folder).glob('*.zip'))
print(json.dumps(dict(member_structure_evals=3, passed=True)))
