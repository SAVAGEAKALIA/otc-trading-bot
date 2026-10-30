import numpy as np
import pandas as pd
import pytest

from trading_platform.research.studies.otc_feature_matrix import assign_split, build_matrix

TF = 120
START = pd.Timestamp("2026-09-01", tz="UTC").value // 10**6


def _candles(n=400, assets=("A-OTC", "B-OTC"), seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for a in assets:
        px = 1.0
        for i in range(n):
            o = px
            c = o * float(np.exp(rng.normal(0, 1e-3)))
            h, l = max(o, c) * 1.0005, min(o, c) * 0.9995
            rows.append((a, START + i * TF * 1000, o, h, l, c))
            px = c
    return pd.DataFrame(rows, columns=["asset", "start_ms", "open", "high", "low", "close"])


def _mood(candles, seed=1):
    rng = np.random.default_rng(seed)
    ms = np.arange(candles.start_ms.min(), candles.start_ms.max() + TF * 1000, 30_000)
    return pd.DataFrame([(a, int(t), rng.random()) for a in candles.asset.unique() for t in ms],
                        columns=["asset", "mood_ms", "call"])


def _feature_cols(df):
    return [c for c in df.columns if c not in ("y", "split")]


def test_features_do_not_change_when_future_is_rewritten():
    candles, mood = _candles(), _mood(_candles())
    cut = START + 300 * TF * 1000
    base = build_matrix(candles, TF, mood)

    future = candles.start_ms >= cut
    tampered = candles.copy()
    # Reshape (not just rescale) every future candle: ratios and vol must change.
    noise = np.random.default_rng(99).normal(0, 5e-3, future.sum())
    tampered.loc[future, "close"] *= np.exp(noise)
    tampered.loc[future, "high"] = tampered.loc[future, ["open", "close"]].max(axis=1) * 1.002
    tampered.loc[future, "low"] = tampered.loc[future, ["open", "close"]].min(axis=1) * 0.9999
    tampered_mood = mood.copy()
    tampered_mood.loc[tampered_mood.mood_ms >= cut - 1000, "call"] = 0.0
    other = build_matrix(tampered, TF, tampered_mood)

    # Rows whose label candle opens before the cut saw no tampered data at all.
    keep = lambda d: d[d.target_start_ms < cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(keep(base)[_feature_cols(base)], keep(other)[_feature_cols(other)])
    pd.testing.assert_series_equal(keep(base).y, keep(other).y)
    assert len(keep(base)) > 400


def test_label_is_next_candle_direction_and_gaps_drop_rows():
    c = _candles(n=60, assets=("A-OTC",))
    c.loc[c.index >= 40, "start_ms"] += TF * 1000  # one missing slot before candle 40
    m = build_matrix(c, TF, None)
    slots = set((m.target_start_ms - START) // (TF * 1000))
    # Candle 39 is followed by slot 41 (slot 40 is missing), so it has no label.
    assert 41 not in slots and {39, 42} <= slots
    row = m.iloc[0]
    nxt = c[c.start_ms == row.target_start_ms].iloc[0]
    assert row.y == int(nxt.close > nxt.open)


def test_mood_must_precede_target_open_and_be_fresh():
    c = _candles(n=80, assets=("A-OTC",))
    target = int(c.start_ms.iloc[60])
    mood = pd.DataFrame({"asset": "A-OTC", "mood_ms": [target - 1000, target - 500], "call": [0.9, 0.1]})
    m = build_matrix(c, TF, mood).set_index("target_start_ms")
    assert m.loc[target, "mood_centered"] == pytest.approx(0.4)  # the 500ms-before sample is too late
    stale = target + 2 * TF * 1000
    assert np.isnan(m.loc[stale, "mood_centered"])  # older than 60s


def test_frozen_rubric_split_boundaries_and_purge():
    ms = lambda s: pd.Timestamp(s).value // 10**6
    s = assign_split(pd.Series([ms("2026-09-07T23:58Z"), ms("2026-09-08T00:30Z"), ms("2026-09-08T01:00Z"),
                                ms("2026-09-21T23:58Z"), ms("2026-09-22T00:10Z"), ms("2026-09-22T01:00Z"),
                                ms("2026-10-08T06:10Z")]))
    assert s.tolist() == ["train", "purged", "validation", "validation", "purged", "holdout", "holdout"]
