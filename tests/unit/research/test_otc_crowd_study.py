import numpy as np
import pandas as pd

from trading_platform.research.studies import otc_crowd_study as cs

TF = 120_000


def _rows_and_mood(n_slots=20_000, fade_edge=0.5, assets=("A", "B", "C"), seed=0, start=None):
    """Synthetic 2m rows with a crowd reading 30s before each candle; fade wins with prob fade_edge."""
    rng = np.random.default_rng(seed)
    start = start or cs.START_MS
    rows, mood = [], []
    for a in assets:
        for i in range(n_slots):
            t = start + i * TF
            call = float(rng.uniform(0.05, 0.95))
            crowd_long = call > 0.5
            fade_win = rng.random() < fade_edge
            up = (not crowd_long) if fade_win else crowd_long
            rows.append((a, t - TF, t, int(up), float(rng.normal())))
            mood.append((a, t - 30_000, call))
    r = pd.DataFrame(rows, columns=["asset", "start_ms", "target_start_ms", "y", "body_z_0"])
    m = pd.DataFrame(mood, columns=["asset", "mood_ms", "call"])
    p = pd.DataFrame({"asset": list(assets), "payout_ms": start - 1000, "payout": 0.85})
    return r, m, p


def test_fade_label_definition():
    df = pd.DataFrame({"y": [1, 0, 1, 0], "crowd_side": [1, 1, -1, -1]})
    # crowd long & candle up -> follow wins; crowd short & candle up -> fade wins
    assert cs.fade_wins(df).tolist() == [0, 1, 1, 0]


def test_crowd_features_ignore_the_future():
    r, m, p = _rows_and_mood(n_slots=600)
    base = cs.crowd_features(r, m, p)
    cut = cs.START_MS + 400 * TF
    m2 = m.copy()
    m2.loc[m2.mood_ms >= cut - 1000, "call"] = 0.99
    other = cs.crowd_features(r, m2, p)
    cols = [c for c in base.columns if c.startswith(("m", "crowd", "market"))]
    keep = lambda d: d[d.target_start_ms < cut].reset_index(drop=True)[cols]
    pd.testing.assert_frame_equal(keep(base), keep(other))


def test_mood_after_key_is_not_used():
    r, m, p = _rows_and_mood(n_slots=50, assets=("A",))
    m = m.assign(mood_ms=m.mood_ms + 29_500)  # 0.5s before the candle opens: too late
    assert cs.crowd_features(r, m, p).empty or cs.crowd_features(r, m, p)["m0"].isna().all()


def test_grid_finds_planted_fade_edge_and_rejects_noise():
    r, m, p = _rows_and_mood(n_slots=54 * 720, fade_edge=0.60)
    df = cs.crowd_features(r, m, p)
    res = cs.score(cs.run_grid(df))
    assert res["candidate"] and res["unseen"]["fade_share"] == 1.0

    r, m, p = _rows_and_mood(n_slots=54 * 720, fade_edge=0.50, seed=3)
    res = cs.score(cs.run_grid(cs.crowd_features(r, m, p)))
    assert not res["candidate"]


def test_grid_selection_uses_only_prior_weeks():
    # An edge that only exists from week 3 on cannot be traded before it has a prior record.
    r, m, p = _rows_and_mood(n_slots=54 * 720, fade_edge=0.5, seed=5)
    df = cs.crowd_features(r, m, p)
    late = df.target_start_ms >= cs.WEEKS[3]
    rng = np.random.default_rng(1)
    flip = late & (rng.random(len(df)) < 0.3)
    df.loc[flip, "y"] = (df.loc[flip, "crowd_side"] == -1).astype(int)  # force fade wins
    tr = cs.run_grid(df)
    assert tr.empty or tr.week.min() >= 4
