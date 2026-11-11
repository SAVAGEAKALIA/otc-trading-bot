"""Does the real interbank FX market lead IQ Option's OTC feed on weekdays?

Real prices: public Dukascopy hourly tick files (bi5 = LZMA of 20-byte big-endian records
ms_offset:uint32, ask:uint32, bid:uint32, ask_vol:float32, bid_vol:float32; price scale 1e5,
JPY pairs 1e3). Files are fetched outside the repo (rate-limited, sequential) and never committed.

Pre-registered test (written before looking at the multi-day data): for each pair, the real
market's return over bar t (close-to-close, 120s grid) predicts the sign of the OTC return over bar
t+1. Reported: correlations at lags -3..+3, and the hit rate of the rule
"OTC next bar direction = sign(real return of bar t)" with a Wilson interval.
"""
from __future__ import annotations

import lzma
import re
import struct
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

NAME = re.compile(r"(?P<pair>[A-Z]{6})_(?P<day>\d{4}-\d{2}-\d{2})_(?P<hour>\d{2})\.bi5$")


def decode_bi5(blob: bytes, hour_start: float, scale: float) -> np.ndarray:
    """(n, 2) array of (unix seconds, mid price)."""
    if not blob:
        return np.empty((0, 2))
    raw = lzma.decompress(blob)
    n = len(raw) // 20
    rec = struct.unpack(">" + "3I2f" * n, raw[: n * 20])
    arr = np.array(rec, dtype=np.float64).reshape(n, 5)
    return np.stack([hour_start + arr[:, 0] / 1000.0, (arr[:, 1] + arr[:, 2]) / 2 / scale], axis=1)


def load_real(folder: Path, pair: str, tf: int = 120) -> pd.Series:
    """Last real mid in each tf bucket (bucket start, UTC seconds)."""
    scale = 1e3 if pair.endswith("JPY") else 1e5
    parts = []
    for path in sorted(folder.glob(f"{pair}_*.bi5")):
        m = NAME.search(path.name)
        start = datetime.fromisoformat(m["day"]).replace(tzinfo=timezone.utc).timestamp() + 3600 * int(m["hour"])
        try:
            parts.append(decode_bi5(path.read_bytes(), start, scale))
        except lzma.LZMAError:  # truncated or error-page download: skip, the hour is simply missing
            continue
    ticks = np.concatenate(parts) if parts else np.empty((0, 2))
    s = pd.Series(ticks[:, 1], index=(ticks[:, 0] // tf * tf).astype(np.int64))
    return s.groupby(level=0).last()


def lead_lag(otc_close: pd.Series, real_close: pd.Series, tf: int = 120) -> dict:
    """otc_close indexed by bar start; real_close by bucket start. Both are bar-end prices."""
    j = pd.concat([otc_close.rename("otc"), real_close.rename("real")], axis=1).dropna()
    j = j[np.diff(j.index, prepend=j.index[0] - tf) == tf]  # keep only consecutive bars
    full = pd.concat([otc_close.rename("otc"), real_close.rename("real")], axis=1)
    grid = full.reindex(np.arange(full.index.min(), full.index.max() + tf, tf))
    ro, rr = np.log(grid.otc).diff(), np.log(grid.real).diff()
    corr = {lag: float(ro.corr(rr.shift(lag))) for lag in range(-3, 4)}  # lag>0: real leads OTC
    nxt = np.sign(ro.shift(-1))
    sig = np.sign(rr)
    ok = nxt.notna() & sig.notna() & (nxt != 0) & (sig != 0)
    hits = int((nxt[ok] == sig[ok]).sum())
    n = int(ok.sum())
    from .metrics import wilson

    return {"bars_both": int(len(j)), "corr_by_lag": corr, "rule_trades": n, "rule_hits": hits,
            "rule_hit_rate": hits / n if n else None, "rule_wilson95": list(wilson(hits, n)) if n else None,
            "level_diff_mean": float((j.otc - j.real).mean()) if len(j) else None,
            "level_diff_std": float((j.otc - j.real).std()) if len(j) else None}
