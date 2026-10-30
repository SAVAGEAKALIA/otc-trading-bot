"""Causal feature matrix for next-candle direction on IQ Option OTC candles.

One row per (asset, candle t). Features use candles <= t and mood observed
strictly before the next candle opens. The label is the direction of candle
t+1 (close vs open), kept only when t+1 directly follows t. Dojis are dropped
because the broker refunds them.

Usage:
    python -m trading_platform.research.studies.otc_feature_matrix \
        --historical data/ml/mtf_candles.parquet --realtime rt_ohlc.csv.gz \
        --mood mood.csv.gz --out otc_matrix.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

BODY_LAGS = 30
WICK_LAGS = 10
SPLITS = (  # frozen rubric, /tmp/otc-kaggle-edge/critique/rubric.md
    ("train", None, "2026-09-08T00:00:00Z"),
    ("validation", "2026-09-08T01:00:00Z", "2026-09-22T00:00:00Z"),
    ("holdout", "2026-09-22T01:00:00Z", None),
)
MOOD_MAX_AGE_MS = 60_000


def clean_mood(raw: pd.DataFrame) -> pd.DataFrame:
    """Average duplicate samples and drop readings of exactly 0 or 1.

    About 29% of raw samples are exactly 0 or 1. They behave like no-volume
    snapshots, not real one-sided crowds (contrarian wins ~51% on them), so
    they are dropped. The previous genuine reading within 60s is used instead.
    """
    mood = raw.groupby(["asset", "mood_ms"], as_index=False)["call"].mean()
    return mood[(mood["call"] > 0) & (mood["call"] < 1)].reset_index(drop=True)


def _ms(ts: str) -> int:
    return int(pd.Timestamp(ts).value // 1_000_000)


def assign_split(target_start_ms: pd.Series) -> pd.Series:
    split = pd.Series("purged", index=target_start_ms.index, dtype=object)
    for name, start, end in SPLITS:
        mask = pd.Series(True, index=target_start_ms.index)
        if start:
            mask &= target_start_ms >= _ms(start)
        if end:
            mask &= target_start_ms < _ms(end)
        split[mask] = name
    return split


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / down.replace(0, np.nan))


def asset_features(c: pd.DataFrame, tf_sec: int) -> pd.DataFrame:
    """Features for one asset's candles of one timeframe, sorted by start_ms."""
    c = c.sort_values("start_ms").reset_index(drop=True)
    o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
    body = np.log(cl / o)
    rng = np.log(h / l).replace(0, np.nan)
    vol = body.rolling(50, min_periods=20).std()
    f = pd.DataFrame({"start_ms": c["start_ms"]})
    bz = body / vol
    for k in range(BODY_LAGS):
        f[f"body_z_{k}"] = bz.shift(k)
    upper = (h - np.maximum(o, cl)) / (h - l).replace(0, np.nan)
    lower = (np.minimum(o, cl) - l) / (h - l).replace(0, np.nan)
    for k in range(WICK_LAGS):
        f[f"upper_wick_{k}"] = upper.shift(k)
        f[f"lower_wick_{k}"] = lower.shift(k)
    f["range_z"] = rng / rng.rolling(50, min_periods=20).mean()
    for k in (3, 5, 10, 20, 60):
        f[f"ret_{k}_z"] = np.log(cl / cl.shift(k)) / (vol * np.sqrt(k))
    f["rsi14"] = _rsi(cl)
    for n in (20, 50):
        f[f"dist_sma{n}_z"] = np.log(cl / cl.rolling(n).mean()) / vol
    lo20, hi20 = l.rolling(20).min(), h.rolling(20).max()
    f["pos_range20"] = (cl - lo20) / (hi20 - lo20).replace(0, np.nan)
    f["vol_ratio_10_50"] = body.rolling(10).std() / vol
    sign = np.sign(body)
    run_id = (sign != sign.shift()).cumsum()
    f["streak"] = sign * sign.groupby(run_id).cumcount().add(1)
    f["gap_before"] = (c["start_ms"].diff() != tf_sec * 1000).astype(np.int8)

    nxt_start = c["start_ms"].shift(-1)
    f["target_start_ms"] = nxt_start
    f["y"] = np.sign(cl.shift(-1) - o.shift(-1))
    f["label_ok"] = (nxt_start - c["start_ms"]) == tf_sec * 1000
    f["body_raw"] = body  # for the cross-asset market factor only
    return f


def add_mood(frame: pd.DataFrame, mood: pd.DataFrame) -> pd.DataFrame:
    """Latest mood observed at least 1s before the target candle opens, at most 60s stale."""
    m = mood.sort_values("mood_ms")
    frame = frame.sort_values("target_start_ms").copy()
    frame["mood_key"] = frame["target_start_ms"] - 1000
    out = pd.merge_asof(frame, m, left_on="mood_key", right_on="mood_ms", by="asset",
                        direction="backward", tolerance=MOOD_MAX_AGE_MS)
    out["mood_age_s"] = (out["mood_key"] - out["mood_ms"]) / 1000
    for lag_s in (120, 600):
        lagged = m.rename(columns={"mood_ms": f"m{lag_s}_ms", "call": f"call_{lag_s}"})
        out[f"mk{lag_s}"] = out["mood_key"] - lag_s * 1000
        out = pd.merge_asof(out.sort_values(f"mk{lag_s}"), lagged, left_on=f"mk{lag_s}",
                            right_on=f"m{lag_s}_ms", by="asset", direction="backward",
                            tolerance=MOOD_MAX_AGE_MS)
        out[f"mood_delta_{lag_s}"] = out["call"] - out[f"call_{lag_s}"]
        out = out.drop(columns=[f"mk{lag_s}", f"m{lag_s}_ms", f"call_{lag_s}"])
    out["mood_centered"] = out["call"] - 0.5
    return out.drop(columns=["mood_key", "mood_ms", "call"])


def build_matrix(candles: pd.DataFrame, tf_sec: int, mood: pd.DataFrame | None) -> pd.DataFrame:
    """candles: asset, start_ms, open, high, low, close for one timeframe."""
    parts = []
    for asset, g in candles.groupby("asset", sort=True):
        f = asset_features(g, tf_sec)
        f["asset"] = asset
        parts.append(f)
    df = pd.concat(parts, ignore_index=True)
    market = df.groupby("start_ms")["body_raw"].transform("mean")
    df["market_body_z"] = market / df.groupby("asset")["body_raw"].transform(lambda s: s.rolling(50, min_periods=20).std())
    df["rel_body_z"] = df["body_z_0"] - df["market_body_z"]
    df = df.drop(columns="body_raw")
    df = df[df["label_ok"] & (df["y"] != 0)].dropna(subset=["y"]).drop(columns="label_ok")
    df["target_start_ms"] = df["target_start_ms"].astype(np.int64)
    df["y"] = (df["y"] > 0).astype(np.int8)
    ts = pd.to_datetime(df["target_start_ms"], unit="ms", utc=True)
    df["hour_sin"] = np.sin(2 * np.pi * ts.dt.hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * ts.dt.hour / 24)
    df["minute_sin"] = np.sin(2 * np.pi * ts.dt.minute / 60)
    df["minute_cos"] = np.cos(2 * np.pi * ts.dt.minute / 60)
    df["dow"] = ts.dt.dayofweek.astype(np.int8)
    if mood is not None:
        df = add_mood(df, mood)
    else:
        df[["mood_age_s", "mood_delta_120", "mood_delta_600", "mood_centered"]] = np.nan
    df["asset_id"] = df["asset"].astype("category").cat.codes.astype(np.int16)
    df["tf_sec"] = tf_sec
    df["split"] = assign_split(df["target_start_ms"])
    df = df[df["split"] != "purged"]
    floats = df.select_dtypes("float64").columns
    df[floats] = df[floats].astype(np.float32)
    return df.sort_values(["target_start_ms", "asset"]).reset_index(drop=True)


def load_candles(historical: Path, realtime: Path) -> pd.DataFrame:
    h = pd.read_parquet(historical)
    ts = pd.to_datetime(h["timestamp"], utc=True)
    h = pd.DataFrame({
        "asset": h["asset"], "tf": h["timeframe"],
        "start_ms": (ts - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1),
        "open": h["open"], "high": h["max"], "low": h["min"], "close": h["close"],
    })
    r = pd.read_csv(realtime, names=["asset", "tf", "start_ms", "open", "high", "low", "close"])
    # Realtime stream wins wherever both sources cover the same candle.
    both = pd.concat([r, h], ignore_index=True).drop_duplicates(["asset", "tf", "start_ms"], keep="first")
    return both


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--historical", type=Path, required=True)
    p.add_argument("--realtime", type=Path, required=True)
    p.add_argument("--mood", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--timeframes", type=int, nargs="+", default=[120, 300])
    a = p.parse_args(argv)
    candles = load_candles(a.historical, a.realtime)
    mood = pd.read_csv(a.mood, names=["asset", "itype", "mood_ms", "call"])
    mood = clean_mood(mood)
    frames = [build_matrix(candles[candles["tf"] == tf].drop(columns="tf"), tf, mood) for tf in a.timeframes]
    out = pd.concat(frames, ignore_index=True)
    out.to_parquet(a.out, index=False)
    print(out.groupby(["tf_sec", "split"]).agg(rows=("y", "size"), p_up=("y", "mean"),
                                               mood_cov=("mood_centered", lambda s: s.notna().mean())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
