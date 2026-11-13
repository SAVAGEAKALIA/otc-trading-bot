"""Causal trigger detectors for the frozen family. No function here reads a future price.

Every detector returns a DataFrame with columns:
  hid, asset, decision_ms, side (+1 call / -1 put), expiry_s, product, cluster
Candle triggers decide at the bar close (bar start + timeframe). Event triggers decide at the
receipt time of the event that fires them. `non_overlapping` then drops any event whose entry falls
before the previous kept trade's expiry on the same hypothesis and asset (no outcome input).

Candle features are computed here, not taken from the lab, so that every scale uses PRIOR data only:
  r      = log close return of the bar (NaN on the first bar of a contiguous run)
  vol60  = standard deviation of the previous 60 returns (excludes the current bar)
  z0     = r / vol60
  mkt0   = leave-one-out mean of the other pairs' z0 at the same bar
  gap    = (log c - mean log c over the last 720 bars) / (vol60 * sqrt(720)); the 720 bars must
           span at most 1.1 days of clock time (allows the daily feed restart, rejects outages)
  posr20 = (c - low of the last 20 bars) / (high - low of the last 20 bars), last 20 bars contiguous
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import spec

EVENT_COLUMNS = ["hid", "asset", "decision_ms", "side", "expiry_s", "product", "cluster"]
TF2, TF5 = 120, 300
LOOKBACK = 64
ANCHOR_BARS = 720
ANCHOR_MAX_SPAN_S = int(1.1 * 86400)


def _events(hid: str, frame: pd.DataFrame) -> pd.DataFrame:
    h = spec.BY_ID[hid]
    cluster = frame["cluster"] if "cluster" in frame else frame["decision_ms"]
    out = pd.DataFrame({
        "hid": hid, "asset": frame["asset"].to_numpy(), "decision_ms": frame["decision_ms"].to_numpy(np.int64),
        "side": frame["side"].to_numpy(np.int8), "expiry_s": h.expiry_s, "product": h.product,
        "cluster": cluster.to_numpy(np.int64),
    })
    return out[EVENT_COLUMNS].sort_values(["decision_ms", "asset"]).reset_index(drop=True)


def empty(hid: str = "") -> pd.DataFrame:
    frame = pd.DataFrame({c: pd.Series(dtype="object" if c in ("hid", "asset", "product") else "int64")
                          for c in EVENT_COLUMNS})
    return frame


def non_overlapping(events: pd.DataFrame) -> pd.DataFrame:
    """Keep an event only if its entry is at or after the previous kept trade's expiry (same hid, asset)."""
    if events.empty:
        return events
    keep = []
    for _, g in events.sort_values(["hid", "asset", "decision_ms"]).groupby(["hid", "asset"], sort=False):
        busy_until = -1
        for idx, d, exp in zip(g.index, g.decision_ms.to_numpy(np.int64), g.expiry_s.to_numpy(np.int64)):
            entry = d + spec.ENTRY_DELAY_MS
            if entry >= busy_until:
                keep.append(idx)
                busy_until = entry + exp * 1000
    return events.loc[sorted(keep)].sort_values(["decision_ms", "asset"]).reset_index(drop=True)


# ---------------------------------------------------------------- candle features

def _asset_frame(b: pd.DataFrame, tf: int) -> pd.DataFrame:
    b = b.sort_values("t").reset_index(drop=True)
    t = b.t.to_numpy(np.int64)
    run = np.cumsum(np.diff(t, prepend=t[0] - tf) != tf)
    pos = pd.Series(run).groupby(run).cumcount().to_numpy()
    c, h, l = (b[k].to_numpy(np.float64) for k in "chl")
    lc = pd.Series(np.log(c))
    r = lc.diff()
    r[pos == 0] = np.nan
    vol60 = r.shift(1).rolling(60).std().clip(lower=1e-7)
    out = pd.DataFrame({"asset": b.asset.to_numpy(), "t": t, "c": c, "run": run, "pos": pos,
                        "z0": (r / vol60).to_numpy(), "vol60": vol60.to_numpy()})
    anchor = lc.rolling(ANCHOR_BARS, min_periods=ANCHOR_BARS).mean()
    span_ok = (pd.Series(t) - pd.Series(t).shift(ANCHOR_BARS - 1)) <= ANCHOR_MAX_SPAN_S
    out["gap"] = np.where(span_ok, (lc - anchor) / (vol60 * np.sqrt(ANCHOR_BARS)), np.nan)
    hi20 = pd.Series(h).rolling(20).max()
    lo20 = pd.Series(l).rolling(20).min()
    contiguous20 = pos >= 19
    rng = (hi20 - lo20).replace(0, np.nan)
    out["posr20"] = np.where(contiguous20, (pd.Series(c) - lo20) / rng, np.nan)
    out["valid"] = pos >= LOOKBACK
    out["decision_ms"] = (t + tf) * 1000
    return out


def candle_frame(bars: pd.DataFrame, tf: int = TF2) -> pd.DataFrame:
    frames = [_asset_frame(g, tf) for _, g in bars.groupby("asset", sort=True)]
    f = pd.concat(frames, ignore_index=True)
    z = f.pivot(index="t", columns="asset", values="z0")
    total, count = z.sum(axis=1, min_count=1), z.notna().sum(axis=1)
    loo = (-z).add(total, axis=0).div((count - 1).where(count > 1), axis=0)
    mkt0 = loo.stack(future_stack=True).rename("mkt0").reset_index()
    f = f.merge(mkt0, on=["t", "asset"], how="left")
    return f.sort_values(["asset", "t"]).reset_index(drop=True)


def thresholds_from_archive(f: pd.DataFrame) -> dict:
    """Frozen thresholds. Reads only z0 and mkt0 (functions of past returns); no label exists here."""
    v = f[f.valid]
    per_asset = {}
    for asset, s in v.groupby("asset").z0:
        a = s.abs().dropna()
        per_asset[asset] = {"z0_q995": float(a.quantile(0.995)), "z0_q999": float(a.quantile(0.999))}
    return {"z0": per_asset, "mkt0_q990": float(v.mkt0.abs().dropna().quantile(0.99))}


def h2(f: pd.DataFrame, thr: dict, key: str = "z0_q995", hid: str = "H2") -> pd.DataFrame:
    v = f[f.valid & f.z0.notna()].copy()
    cut = v.asset.map({a: d[key] for a, d in thr["z0"].items()})
    v = v[cut.notna() & (v.z0.abs() >= cut)]
    v["side"] = -np.sign(v.z0).astype(np.int8)
    return _events(hid, v[v.side != 0])


def h2b(f: pd.DataFrame, thr: dict) -> pd.DataFrame:
    return h2(f, thr, "z0_q999", "H2b")


def h3(f: pd.DataFrame) -> pd.DataFrame:
    g = f[f.valid & f.gap.notna()].copy()
    over = g.gap.abs() > 2.5
    prev_over = over.groupby(g.asset).shift(1, fill_value=False)
    contiguous = g.groupby("asset").t.diff() == TF2
    g = g[over & ~(prev_over & contiguous)]
    g["side"] = -np.sign(g.gap).astype(np.int8)
    return _events("H3", g[g.side != 0])


def h4(bars: pd.DataFrame, offset_frac: float = 0.0) -> pd.DataFrame:
    """Round-number first touch. offset_frac in [0, 1) shifts the lattice (0 = real round numbers).

    Touch: close within 0.01% of the nearest lattice level L. Approach: max |close - L| over the prior
    5 bars >= 8 pips. First touch: no close within 0.01% of L in the prior 30 bars. All 30 prior bars
    must be contiguous (no gap), so 30 bars means 60 minutes.
    """
    rows = []
    for asset, s in bars.sort_values(["asset", "t"]).groupby("asset"):
        c = s.c.to_numpy(np.float64)
        t = s.t.to_numpy(np.int64)
        n = len(c)
        if n < 31:
            continue
        step = 0.5 if "JPY" in asset else 0.005
        pip = 0.01 if "JPY" in asset else 0.0001
        off = offset_frac * step
        lvl = np.round((c - off) / step) * step + off
        near = np.abs(c - lvl) <= c * 1e-4
        run = np.cumsum(np.diff(t, prepend=t[0] - TF2) != TF2)
        pos = pd.Series(run).groupby(run).cumcount().to_numpy()
        for i in np.flatnonzero(near & (pos >= 30)):
            prior = c[i - 30:i]
            if np.any(np.abs(prior - lvl[i]) <= prior * 1e-4):
                continue  # touched this same level within the last 60 minutes
            last5 = c[i - 5:i]
            if np.max(np.abs(last5 - lvl[i])) < 8 * pip:
                continue
            side = 1 if last5.mean() > lvl[i] else -1  # came from above: fade the fall (call)
            rows.append((asset, (t[i] + TF2) * 1000, side))
    if not rows:
        return empty()
    return _events("H4", pd.DataFrame(rows, columns=["asset", "decision_ms", "side"]))


def h5(f: pd.DataFrame, thr: dict) -> pd.DataFrame:
    v = f[f.valid & f.mkt0.notna() & f.z0.notna()].copy()
    v = v[v.mkt0.abs() >= thr["mkt0_q990"]]
    v = v[np.sign(v.z0) == np.sign(v.mkt0)]
    if v.empty:
        return empty()
    v["absz"] = v.z0.abs()
    v = v.sort_values(["decision_ms", "absz", "asset"], ascending=[True, False, True])
    v = v.drop_duplicates("decision_ms", keep="first")  # one trade per timestamp cluster
    v["side"] = -np.sign(v.mkt0).astype(np.int8)
    v["cluster"] = v.decision_ms
    return _events("H5", v[v.side != 0])


def h8(bars5: pd.DataFrame) -> pd.DataFrame:
    f = candle_frame(bars5, TF5)
    v = f[f.valid & f.posr20.notna()].copy()
    v["side"] = np.where(v.posr20 >= 0.999, 1, np.where(v.posr20 <= 0.001, -1, 0)).astype(np.int8)
    return _events("H8", v[v.side != 0])


# ---------------------------------------------------------------- payout, mood and quote events

def clean_payouts(payouts: pd.DataFrame) -> pd.DataFrame:
    """Registered payout source and products only; numeric dtypes even when empty."""
    p = payouts
    if "source" in p:
        p = p[p.source == spec.PAYOUT_SOURCE]
    p = p[p.instrument_type.isin(spec.PAYOUT_PRODUCTS)].dropna(subset=["payout_fraction"])
    return p.assign(received_at_ms=p.received_at_ms.astype(np.int64),
                    payout_fraction=p.payout_fraction.astype(float))


def payout_steps(payouts: pd.DataFrame, direction: int, sample_ms: int = spec.PAYOUT_SAMPLE_MS) -> pd.DataFrame:
    """Asset-level steps of >= 0.03 in `direction` (-1 down, +1 up), either product, merged within 300 s.
    A step counts only if the previous sample of that product is at most 2 sampling intervals old, so an
    outage or a reconnect never looks like a step."""
    p = clean_payouts(payouts).sort_values(["asset", "instrument_type", "received_at_ms"])
    g = p.groupby(["asset", "instrument_type"])
    p = p.assign(d=g.payout_fraction.diff(), age=g.received_at_ms.diff())
    fresh = (p.age > 0) & (p.age <= 2 * sample_ms)
    hit = fresh & ((p.d <= -0.03 + 1e-9) if direction < 0 else (p.d >= 0.03 - 1e-9))
    ev = p[hit].sort_values(["asset", "received_at_ms"])
    gap = ev.groupby("asset").received_at_ms.diff()
    ev = ev[gap.isna() | (gap > spec.PAYOUT_MERGE_MS)]
    return ev[["asset", "received_at_ms"]].rename(columns={"received_at_ms": "decision_ms"}).reset_index(drop=True)


def _with_mood(ev: pd.DataFrame, mood: pd.DataFrame) -> pd.DataFrame:
    if ev.empty or mood.empty:
        return ev.assign(cf=pd.Series(np.nan, index=ev.index, dtype=float))
    mood = mood.assign(received_at_ms=mood.received_at_ms.astype(np.int64), call_fraction=mood.call_fraction.astype(float))
    ev = ev.assign(decision_ms=ev.decision_ms.astype(np.int64))
    m = mood.sort_values("received_at_ms")[["asset", "received_at_ms", "call_fraction"]]
    j = pd.merge_asof(ev.sort_values("decision_ms"), m, left_on="decision_ms", right_on="received_at_ms",
                      by="asset", direction="backward", tolerance=spec.MAX_MOOD_AGE_MS)
    return j.rename(columns={"call_fraction": "cf"}).drop(columns=["received_at_ms"])


def h1(payouts: pd.DataFrame, mood: pd.DataFrame, sample_ms: int = spec.PAYOUT_SAMPLE_MS) -> pd.DataFrame:
    j = _with_mood(payout_steps(payouts, -1, sample_ms), mood)
    j = j[j.cf.notna() & (j.cf != 0.5) & (j.cf > 0.05) & (j.cf < 0.95)].copy()
    j["side"] = np.where(j.cf > 0.5, -1, 1).astype(np.int8)  # against the majority
    return _events("H1", j) if len(j) else empty()


def h6(payouts: pd.DataFrame, mood: pd.DataFrame, sample_ms: int = spec.PAYOUT_SAMPLE_MS) -> pd.DataFrame:
    j = _with_mood(payout_steps(payouts, +1, sample_ms), mood)
    j = j[j.cf.notna() & (j.cf != 0.5)].copy()
    j["side"] = np.where(j.cf > 0.5, 1, -1).astype(np.int8)  # with the majority
    return _events("H6", j) if len(j) else empty()


def h1_control(payouts: pd.DataFrame, mood: pd.DataFrame, sample_ms: int = spec.PAYOUT_SAMPLE_MS) -> pd.DataFrame:
    """Matched mood-only fade: same mood band and side rule as H1, at mood samples with NO payout step on
    the asset in the previous 15 minutes (past steps only, so selection never uses later data), at most
    one per asset per 300 s. Returned with hid H1 so it is labeled exactly like H1."""
    steps = pd.concat([payout_steps(payouts, -1, sample_ms), payout_steps(payouts, +1, sample_ms)], ignore_index=True)
    m = mood[(mood.call_fraction > 0.05) & (mood.call_fraction < 0.95) & (mood.call_fraction != 0.5)]
    keep = []
    for asset, s in m.sort_values(["asset", "received_at_ms"]).groupby("asset"):
        st = np.sort(steps.loc[steps.asset == asset, "decision_ms"].to_numpy(np.int64))
        last = -10**18
        for t, cf in zip(s.received_at_ms.to_numpy(np.int64), s.call_fraction.to_numpy()):
            if t - last < spec.PAYOUT_MERGE_MS:
                continue
            i = np.searchsorted(st, t, side="right")  # steps at or before t
            if i > 0 and t - st[i - 1] <= spec.CONTROL_EXCLUSION_MS:
                continue
            keep.append((asset, t, -1 if cf > 0.5 else 1))
            last = t
    if not keep:
        return empty()
    return _events("H1", pd.DataFrame(keep, columns=["asset", "decision_ms", "side"]))


def h7(quotes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for asset, s in quotes.sort_values(["asset", "received_at_ms"]).groupby("asset"):
        t = s.received_at_ms.to_numpy(np.int64)
        mid = s.mid.to_numpy(np.float64)
        idx = np.flatnonzero(np.diff(t) >= spec.STALL_GAP_MS) + 1
        jump = mid[idx] - mid[idx - 1]
        ok = jump != 0
        rows.append(pd.DataFrame({"asset": asset, "decision_ms": t[idx][ok],
                                  "side": (-np.sign(jump[ok])).astype(np.int8)}))
    if not rows or sum(len(r) for r in rows) == 0:
        return empty()
    return _events("H7", pd.concat(rows, ignore_index=True))
