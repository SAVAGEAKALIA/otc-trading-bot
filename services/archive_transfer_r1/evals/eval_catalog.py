"""Partition the reviewed catalog and prove no archive is skipped or repeated."""
from datetime import timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transfer import WINDOW_START, WINDOW_END, catalog_batch

catalog = Path(__file__).resolve().parents[3] / 'docs/research/crypto-r1-2026-10-31/depth_catalog_inventory.csv'
for batch_days in range(1, 8):
    start = WINDOW_START
    rows = []
    while start <= WINDOW_END:
        end = min(start + timedelta(days=batch_days - 1), WINDOW_END)
        rows.extend(catalog_batch(catalog, start, end))
        start = end + timedelta(days=1)
    assert len(rows) == len({row['url'] for row in rows}) == 360
    assert sum(int(row['size']) for row in rows) == 37950899531
print('PASS: seven batch sizes cover all 360 unique archives')
