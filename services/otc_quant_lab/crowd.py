"""Pre-registered crowd-fade test on the recorded trader-mood stream (Jul 31 - Aug 20 2026).

Frozen in docs/research/otc/2026-10-30-research-direction.md before this lab existed:
bet against the crowd when 0.30 <= |call_fraction - 0.5| < 0.45. No retuning here.

Timing: decision at the close of 120s bar t (= t + 120). The mood value used is the last sample
RECEIVED (received_at_ms) at or before the decision and no older than 60 s. Outcome = close of
bar t+1 vs close of bar t (120 s expiry proxy), ties refunded.
Second, finer variant: 1 s realtime candles; entry = last 1 s close at or before decision + 2 s
(execution delay), expiry = last 1 s close at or before entry + 120 s.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import data, features
from .features import DOWN, TIE, UP
from .metrics import trade_summary

BAND = (0.30, 0.45)
MAX_AGE_MS = 60_000


def attach_mood(frame: pd.DataFrame, mood: pd.DataFrame, tf: int = 120) -> pd.DataFrame:
    out = []
    for asset, g in frame.groupby("asset"):
        m = mood[mood.asset == asset].sort_values("received_at_ms")
        if m.empty:
            continue
        g = g.sort_values("t").copy()
        g["decision_ms"] = (g.t + tf) * 1000
        j = pd.merge_asof(g, m[["received_at_ms", "call_fraction"]], left_on="decision_ms",
                          right_on="received_at_ms", direction="backward")
        j.loc[(j.decision_ms - j.received_at_ms) > MAX_AGE_MS, "call_fraction"] = np.nan
        out.append(j)
    return pd.concat(out, ignore_index=True)


def fade_signal(call_fraction: np.ndarray) -> np.ndarray:
    """+1 bet up, -1 bet down, 0 abstain."""
    d = np.abs(call_fraction - 0.5)
    inside = (d >= BAND[0]) & (d < BAND[1])
    return np.where(inside & (call_fraction > 0.5), -1, np.where(inside & (call_fraction < 0.5), 1, 0))


def bar_outcomes(frame: pd.DataFrame, signal: np.ndarray) -> np.ndarray:
    y = frame["y1"].to_numpy()
    take = (signal != 0) & (y != -2)
    out = np.where(y == TIE, -1, np.where((y == UP) == (signal > 0), 1, 0))
    return np.where(take, out, -9)


def second_outcomes(frame: pd.DataFrame, signal: np.ndarray, seconds: pd.DataFrame,
                    delay: int = 2, expiry: int = 120) -> np.ndarray:
    out = np.full(len(frame), -9)
    for asset, idx in frame.groupby("asset").groups.items():
        s = seconds[seconds.asset == asset].sort_values("t")
        if s.empty:
            continue
        ts, cs = s.t.to_numpy(), s.c.to_numpy()
        idx = np.asarray(idx)
        entry_t = frame.t.to_numpy()[idx] + 120 + delay
        i0 = np.searchsorted(ts, entry_t, side="right") - 1
        i1 = np.searchsorted(ts, entry_t + expiry, side="right") - 1
        ok = (i0 >= 0) & (i1 >= 0) & (signal[idx] != 0)
        ok &= (entry_t - ts[np.clip(i0, 0, None)] <= 3) & (entry_t + expiry - ts[np.clip(i1, 0, None)] <= 3)
        e, x = cs[np.clip(i0, 0, None)], cs[np.clip(i1, 0, None)]
        res = np.where(x == e, -1, np.where((x > e) == (signal[idx] > 0), 1, 0))
        out[idx[ok]] = res[ok]
    return out


def run() -> dict:
    bars = data.load_realtime(120)
    frame = features.build(bars, 120, (1,))
    frame = attach_mood(frame, data.load_mood())
    signal = fade_signal(frame.call_fraction.to_numpy())
    result = {"rows": int(len(frame)), "rows_with_fresh_mood": int(frame.call_fraction.notna().sum()),
              "band": BAND, "signals": int((signal != 0).sum())}
    seconds = data.load_realtime(1)
    for name, outcome in (("bar_proxy", bar_outcomes(frame, signal)),
                          ("one_second_delay2s", second_outcomes(frame, signal, seconds))):
        traded = outcome != -9
        tr = frame[traded].assign(outcome=outcome[traded]).sort_values("t")
        result[name] = trade_summary(tr.outcome.to_numpy(), tr.day.to_numpy(), trials=1)
        by_asset = tr.groupby("asset").outcome.apply(lambda o: float((o == 1).sum() / max((o >= 0).sum(), 1)))
        result[name]["win_rate_by_asset"] = by_asset.round(4).to_dict()
    return result


if __name__ == "__main__":
    import json

    print(json.dumps(run(), indent=2, default=float))
