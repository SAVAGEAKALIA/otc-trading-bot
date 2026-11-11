"""Causal features and binary outcome labels.

Timing contract (tested in tests/test_causality.py):
- A row is bar t (start `t`, closes at `t + tf`). The decision is made at `t + tf`.
- Features use bars whose close <= t + tf only. Rolling windows look backward.
- Entry price proxy = close of bar t. Outcome at horizon h = close of bar t+h vs entry.
- A label exists only when bars t..t+h are contiguous (no missing bar in between).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LOOKBACK = 64  # rows need this many contiguous prior bars; > every rolling window below
SEQ_LEN = 32
UP, DOWN, TIE, UNKNOWN = 1, 0, -1, -2

CURRENCIES = ["AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "NZD", "USD"]

BASE_FEATURES = (
    [f"z{k}" for k in range(10)]
    + [f"{name}{k}" for k in range(5) for name in ("body", "upw", "low", "rng")]
    + ["ret3", "ret5", "ret10", "ret20", "ret60", "zsma20", "zsma50", "rsi14", "posr20",
       "eff20", "volr", "streak", "pat3", "pat5", "hour_sin", "hour_cos", "dow"]
)
CROSS_FEATURES = ["mkt0", "mkt5", "res0", "res5", "res20"]
FEATURES = BASE_FEATURES + CROSS_FEATURES
# Round 2 (critic finding 8): asset identity, clock position finer than the hour, time since the daily
# feed restart. Appended so every FEATURES index stays valid. Volume is 0 in every archived bar: unusable.
CLOCK_FEATURES = ["asset_id", "min_sin", "min_cos", "quad_pos", "since_restart"]
FEATURES_V2 = FEATURES + CLOCK_FEATURES
SEQ_CHANNELS = ["z0", "body0", "upw0", "low0", "rng0"]


def _streak(color: np.ndarray, run: np.ndarray) -> np.ndarray:
    """Signed count of consecutive same-colour bars ending at each row (0 for dojis)."""
    out = np.zeros(len(color), dtype=np.float32)
    for i in range(len(color)):
        if color[i] != 0 and i > 0 and run[i] == run[i - 1] and color[i] == np.sign(out[i - 1]):
            out[i] = out[i - 1] + color[i]
        else:
            out[i] = color[i]
    return np.clip(out, -10, 10)


def asset_features(bars: pd.DataFrame, tf: int, horizons: tuple[int, ...]) -> pd.DataFrame:
    """Per-asset causal features and labels. `bars` must be one asset sorted by t."""
    b = bars.reset_index(drop=True)
    t = b.t.to_numpy()
    run = np.cumsum(np.diff(t, prepend=t[0] - tf) != tf)
    pos = pd.Series(run).groupby(run).cumcount().to_numpy()
    o, h, l, c = (b[k].to_numpy(dtype=np.float64) for k in "ohlc")
    lc = pd.Series(np.log(c))
    r = lc.diff()
    r[pos == 0] = np.nan
    vol60 = r.rolling(60).std().clip(lower=1e-7)
    vol10 = r.rolling(10).std()
    out = pd.DataFrame({"asset": b.asset, "t": t, "run": run, "pos": pos})
    for k in range(10):
        out[f"z{k}"] = (r / vol60).shift(k)
    body = np.log(c / o) / vol60
    upw = np.log(h / np.maximum(o, c)) / vol60
    low = np.log(np.minimum(o, c) / l) / vol60
    rng = np.log(h / l) / vol60
    for k in range(5):
        out[f"body{k}"] = body.shift(k)
        out[f"upw{k}"] = upw.shift(k)
        out[f"low{k}"] = low.shift(k)
        out[f"rng{k}"] = rng.shift(k)
    for k in (3, 5, 10, 20, 60):
        out[f"ret{k}"] = (lc - lc.shift(k)) / (vol60 * np.sqrt(k))
    for k in (20, 50):
        out[f"zsma{k}"] = (lc - np.log(pd.Series(c).rolling(k).mean())) / (vol60 * np.sqrt(k))
    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    out["rsi14"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    hi20 = pd.Series(h).rolling(20).max()
    lo20 = pd.Series(l).rolling(20).min()
    out["posr20"] = (c - lo20) / (hi20 - lo20).replace(0, np.nan)
    path = r.abs().rolling(20).sum()
    out["eff20"] = (lc - lc.shift(20)).abs() / path.replace(0, np.nan)
    out["volr"] = vol10 / vol60
    color = np.sign(c - o).astype(np.int8)
    out["color"] = color
    out["streak"] = _streak(color, run)
    col = pd.Series(color.astype(np.int16) + 1)
    out["pat3"] = col + 3 * col.shift(1) + 9 * col.shift(2)
    out["pat5"] = out["pat3"] + 27 * col.shift(3) + 81 * col.shift(4)
    decision = t + tf
    hour = (decision % 86400) / 3600.0
    out["hour"] = hour.astype(np.float32)
    out["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    out["dow"] = ((decision // 86400) + 4) % 7  # 0 = Monday
    minute = (decision % 3600) / 60.0
    out["min_sin"] = np.sin(2 * np.pi * minute / 60)
    out["min_cos"] = np.cos(2 * np.pi * minute / 60)
    out["quad_pos"] = (decision // tf) % 5  # bar position inside the 5-bar MHI quadrant
    out["since_restart"] = np.log1p(pos.astype(np.float64))
    out["day"] = decision // 86400
    out["r0"] = r
    out["vol60"] = vol60
    out["valid"] = pos >= LOOKBACK
    for hz in horizons:
        future = pd.Series(c).shift(-hz).to_numpy()
        contiguous = pd.Series(run).shift(-hz).to_numpy() == run
        label = np.full(len(c), UNKNOWN, dtype=np.int8)
        label[contiguous & (future > c)] = UP
        label[contiguous & (future < c)] = DOWN
        label[contiguous & (future == c)] = TIE
        out[f"y{hz}"] = label
    return out


def _pair_matrix(assets: list[str]) -> np.ndarray:
    """+1 base / -1 quote design for log pair returns = s_base - s_quote."""
    design = np.zeros((len(assets), len(CURRENCIES)))
    for i, asset in enumerate(assets):
        pair = asset.split("-")[0]
        design[i, CURRENCIES.index(pair[:3])] = 1.0
        design[i, CURRENCIES.index(pair[3:6])] = -1.0
    return design


def cross_asset(frame: pd.DataFrame, tf: int) -> pd.DataFrame:
    """Market mean (excluding self) and currency-strength residuals, aligned on bar time."""
    zmat = frame.pivot(index="t", columns="asset", values="z0")
    rmat = frame.pivot(index="t", columns="asset", values="r0")
    grid = np.arange(zmat.index.min(), zmat.index.max() + tf, tf)
    zmat = zmat.reindex(grid)
    rmat = rmat.reindex(grid)
    count = zmat.notna().sum(axis=1)
    total = zmat.sum(axis=1)
    mkt0 = (-zmat).add(total, axis=0).div((count - 1).where(count > 1), axis=0)
    mkt5 = mkt0.rolling(5).sum()
    assets = list(rmat.columns)
    design = _pair_matrix(assets)
    values = rmat.to_numpy()
    complete = ~np.isnan(values).any(axis=1)
    resid = np.full(values.shape, np.nan)
    projector = design @ np.linalg.pinv(design)
    resid[complete] = values[complete] - values[complete] @ projector.T
    vol = frame.pivot(index="t", columns="asset", values="vol60").reindex(grid).to_numpy()
    res0 = pd.DataFrame(resid / vol, index=grid, columns=assets)
    parts = {"mkt0": mkt0, "mkt5": mkt5, "res0": res0,
             "res5": res0.rolling(5).sum(), "res20": res0.rolling(20).sum()}
    long = [part.stack(future_stack=True).rename(name) for name, part in parts.items()]
    joined = pd.concat(long, axis=1)
    joined.index.names = ["t", "asset"]
    return joined.reset_index()


def build(bars: pd.DataFrame, tf: int, horizons: tuple[int, ...]) -> pd.DataFrame:
    frames = [asset_features(group, tf, horizons) for _, group in bars.groupby("asset", sort=True)]
    frame = pd.concat(frames, ignore_index=True)
    frame = frame.merge(cross_asset(frame, tf), on=["t", "asset"], how="left")
    floats = frame.select_dtypes("float64").columns
    frame[floats] = frame[floats].astype(np.float32)
    frame["asset_id"] = frame.asset.astype("category").cat.codes.astype(np.int16)
    return frame.sort_values(["asset", "t"]).reset_index(drop=True)


def sequences(frame: pd.DataFrame, rows: np.ndarray) -> np.ndarray:
    """(n, SEQ_LEN, channels) windows ending at each row. Rows must be valid (pos >= LOOKBACK)."""
    channels = np.nan_to_num(frame[SEQ_CHANNELS].to_numpy(np.float32), nan=0.0)
    channels = np.clip(channels, -8, 8)
    offsets = np.arange(-SEQ_LEN + 1, 1)
    return channels[rows[:, None] + offsets[None, :]]
