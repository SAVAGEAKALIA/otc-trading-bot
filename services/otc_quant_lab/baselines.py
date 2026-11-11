"""Deterministic rule baselines. Each returns p_up in {0, 0.5, 1}: 0.5 means abstain.

These are mechanism proxies on 120s/300s broker candles, not the complete live bots.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _p(direction: np.ndarray) -> np.ndarray:
    return np.where(direction > 0, 1.0, np.where(direction < 0, 0.0, 0.5))


def _colors(frame: pd.DataFrame, lags: int) -> np.ndarray:
    """(n, lags) colours of bars t, t-1, ... within each asset (rows sorted by asset, t)."""
    color = frame.color.to_numpy().astype(np.int8)
    asset = frame.asset_id.to_numpy()
    out = np.zeros((len(color), lags), dtype=np.int8)
    for k in range(lags):
        shifted = np.roll(color, k)
        same = np.roll(asset, k) == asset
        shifted[:k] = 0
        out[:, k] = np.where(same, shifted, 0)
    return out


def mhi_minority(frame: pd.DataFrame, tf: int, block_bars: int = 5, quadrant: bool = True) -> np.ndarray:
    """MHI: at a block boundary, trade the minority colour of the block's last three bars."""
    c = _colors(frame, 3)
    ups = (c == 1).sum(1)
    downs = (c == -1).sum(1)
    clean = (ups + downs) == 3
    direction = np.where(clean, np.where(ups < downs, 1, -1), 0)
    if quadrant:
        boundary = ((frame.t.to_numpy() + tf) % (block_bars * tf)) == 0
        direction = np.where(boundary, direction, 0)
    return _p(direction)


def exhaustion(frame: pd.DataFrame, run: int = 4) -> np.ndarray:
    """After `run` consecutive same-colour bars, bet on reversal."""
    s = frame.streak.to_numpy()
    return _p(np.where(s >= run, -1, np.where(s <= -run, 1, 0)))


def trend_follow(frame: pd.DataFrame) -> np.ndarray:
    r = frame.ret10.to_numpy()
    return _p(np.where(r > 1.0, 1, np.where(r < -1.0, -1, 0)))


def mean_reversion(frame: pd.DataFrame, z: float = 2.0) -> np.ndarray:
    d = frame.zsma20.to_numpy()
    return _p(np.where(d > z, -1, np.where(d < -z, 1, 0)))


def breakout(frame: pd.DataFrame) -> np.ndarray:
    """Close at the 20-bar extreme: continuation."""
    p = frame.posr20.to_numpy()
    return _p(np.where(p >= 0.999, 1, np.where(p <= 0.001, -1, 0)))


def false_breakout(frame: pd.DataFrame) -> np.ndarray:
    """Rejection wick near the 20-bar extreme: fade it."""
    p, up, lo, body = (frame[k].to_numpy() for k in ("posr20", "upw0", "low0", "body0"))
    top = (p > 0.7) & (up > 2 * np.abs(body)) & (up > 0.5)
    bottom = (p < 0.3) & (lo > 2 * np.abs(body)) & (lo > 0.5)
    return _p(np.where(top, -1, np.where(bottom, 1, 0)))


def rsi_reversal(frame: pd.DataFrame) -> np.ndarray:
    r = frame.rsi14.to_numpy()
    return _p(np.where(r > 75, -1, np.where(r < 25, 1, 0)))


def baseline_suite(frame: pd.DataFrame, tf: int) -> dict[str, np.ndarray]:
    return {
        "mhi_minority3_quadrant": mhi_minority(frame, tf),
        "mhi_majority3_quadrant": 1.0 - mhi_minority(frame, tf),
        "mhi_minority3_every_bar": mhi_minority(frame, tf, quadrant=False),
        "exhaustion_4": exhaustion(frame, 4),
        "exhaustion_6": exhaustion(frame, 6),
        "trend_follow_ret10": trend_follow(frame),
        "mean_reversion_z2": mean_reversion(frame),
        "breakout_20": breakout(frame),
        "false_breakout_wick": false_breakout(frame),
        "rsi_reversal_75_25": rsi_reversal(frame),
    }
