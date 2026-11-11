"""Gate tests: deterministic, synthetic, fast. Run: .venv-lab/bin/python -m pytest services/otc_quant_lab/tests -q"""
import numpy as np
import pandas as pd
import pytest

from services.otc_quant_lab import bandit, features, metrics, online, regimes, risk, walkforward
from services.otc_quant_lab.features import DOWN, FEATURES, TIE, UNKNOWN, UP

TF = 120
ASSETS = ["EURUSD-OTC", "GBPUSD-OTC", "EURGBP-OTC", "USDJPY-OTC", "EURJPY-OTC", "GBPJPY-OTC"]


def synthetic_bars(n=400, seed=0, gap_at=None):
    rng = np.random.default_rng(seed)
    rows = []
    for a, asset in enumerate(ASSETS):
        c = 1.0 + a + np.cumsum(rng.normal(0, 1e-4, n))
        o = np.concatenate([[c[0]], c[:-1]]) + rng.normal(0, 2e-5, n)
        h = np.maximum(o, c) + np.abs(rng.normal(0, 5e-5, n))
        l = np.minimum(o, c) - np.abs(rng.normal(0, 5e-5, n))
        t = 1_780_000_000 - (1_780_000_000 % 86400) + np.arange(n) * TF
        if gap_at is not None:
            t = np.where(np.arange(n) >= gap_at, t + 10 * TF, t)
        rows.append(pd.DataFrame({"asset": asset, "t": t, "o": o, "h": h, "l": l, "c": c}))
    return pd.concat(rows, ignore_index=True)


def test_features_do_not_see_the_future():
    bars = synthetic_bars()
    base = features.build(bars, TF, (1, 3))
    cut = int(bars.t.min()) + 250 * TF
    mutated = bars.copy()
    later = mutated.t > cut
    mutated.loc[later, ["o", "h", "l", "c"]] *= np.random.default_rng(9).uniform(0.9, 1.1, (later.sum(), 1))
    mutated["h"] = mutated[["o", "h", "c"]].max(axis=1)
    mutated["l"] = mutated[["o", "l", "c"]].min(axis=1)
    again = features.build(mutated, TF, (1, 3))
    rows = base.t <= cut
    a = base.loc[rows, FEATURES].to_numpy()
    b = again.loc[rows, FEATURES].to_numpy()
    np.testing.assert_array_equal(np.isnan(a), np.isnan(b))
    np.testing.assert_allclose(np.nan_to_num(a), np.nan_to_num(b), rtol=0, atol=0)


def test_labels_compare_close_at_expiry_with_entry_close_and_respect_gaps():
    bars = synthetic_bars(n=200, gap_at=120)
    f = features.build(bars, TF, (1, 3))
    g = f[f.asset == "EURUSD-OTC"].reset_index(drop=True)
    c = bars[bars.asset == "EURUSD-OTC"].c.to_numpy()
    i = 80
    assert g.y3[i] == (UP if c[i + 3] > c[i] else DOWN)
    assert g.y1[119] == UNKNOWN  # next bar is across the gap
    assert g.y3[117] == UNKNOWN
    assert g.y3[116] != UNKNOWN
    assert not g.valid[120 + features.LOOKBACK - 1] and g.valid[120 + features.LOOKBACK]


def test_tie_label():
    bars = synthetic_bars(n=150)
    m = bars.asset == "EURUSD-OTC"
    idx = bars[m].index
    bars.loc[idx[101], "c"] = bars.loc[idx[100], "c"]
    bars.loc[idx[101], ["h", "l"]] = [bars.loc[idx[101], ["o", "c", "h"]].max(), bars.loc[idx[101], ["o", "c", "l"]].min()]
    f = features.build(bars, TF, (1,))
    assert f[f.asset == "EURUSD-OTC"].y1.iloc[100] == TIE


def test_currency_residual_is_zero_for_consistent_cross_rates():
    rng = np.random.default_rng(1)
    t = np.arange(300) * TF
    strength = {c: np.cumsum(rng.normal(0, 1e-4, 300)) for c in features.CURRENCIES}
    rows = []
    for asset in ASSETS:
        lc = strength[asset[:3]] - strength[asset[3:6]]
        c = np.exp(lc)
        rows.append(pd.DataFrame({"asset": asset, "t": t, "o": c, "h": c * 1.0001, "l": c * 0.9999, "c": c}))
    f = features.build(pd.concat(rows), TF, (1,))
    assert np.nanmax(np.abs(f.res0.to_numpy())) < 1e-3


def test_wilson_and_breakeven():
    lo, hi = metrics.wilson(540, 1000)
    assert lo == pytest.approx(0.50902, abs=1e-4) and hi == pytest.approx(0.57066, abs=1e-4)
    assert metrics.breakeven(0.84) == pytest.approx(0.543478, abs=1e-6)
    assert metrics.wilson_lower_one_sided(540, 1000, 0.05) == pytest.approx(metrics.wilson(540, 1000, 0.90)[0])


def test_unit_returns_streaks_drawdown():
    out = np.array([1, 0, 0, -1, 0, 1, 0])
    np.testing.assert_allclose(metrics.unit_returns(out, 0.84), [0.84, -1, -1, 0, -1, 0.84, -1])
    assert metrics.max_consecutive_losses(out) == 3  # tie does not break a losing run
    assert metrics.max_drawdown(np.array([1.0, -2.0, -1.0, 0.5])) == pytest.approx(3.0)


def test_day_block_bootstrap_brackets_mean():
    rng = np.random.default_rng(0)
    v = rng.normal(0.1, 1, 5000)
    d = np.repeat(np.arange(50), 100)
    lo, hi = metrics.day_block_bootstrap(v, d)
    assert lo < v.mean() < hi


def test_splits_are_chronological_with_purges():
    folds, final = walkforward.lab_splits(np.arange(1000, 1121))
    for s in folds + [final]:
        assert s.train[1] < s.inner[0] and s.inner[1] < s.test[0]
        assert s.inner[0] - s.train[1] >= 2 and s.test[0] - s.inner[1] >= 2  # purge + embargo
    assert final.test[0] > folds[-1].test[1]
    assert all(a.test[1] <= b.test[0] for a, b in zip(folds, folds[1:]))


def test_non_overlapping_one_position_per_asset():
    asset = np.array(["A", "A", "A", "B", "A"])
    t = np.array([0, 60, 240, 60, 360])
    keep = walkforward.non_overlapping(asset, t, 240)
    assert keep.tolist() == [True, False, True, True, False]


def test_pbo_low_for_true_skill_high_for_noise():
    rng = np.random.default_rng(3)
    noise = rng.normal(0, 1, (16, 40))
    assert walkforward.pbo_cscv(noise)["pbo"] > 0.3
    skill = noise.copy()
    skill[:, 7] += 3.0
    assert walkforward.pbo_cscv(skill)["pbo"] < 0.05


def test_platt_identity_like_on_calibrated_input():
    rng = np.random.default_rng(4)
    p = rng.uniform(0.3, 0.7, 20000)
    y = (rng.random(20000) < p).astype(int)
    f = walkforward.platt(p, y)
    assert np.max(np.abs(f(np.array([0.4, 0.6])) - [0.4, 0.6])) < 0.03


def test_state_table_learns_pattern_probability():
    x = np.zeros((4000, len(FEATURES)), dtype=np.float32)
    x[:, FEATURES.index("pat3")] = np.tile([0, 1], 2000)
    y = np.tile([1, 0], 2000)
    m = regimes.Pattern("pat3", 27).fit(x, y)
    p = m.predict(x[:2])
    assert p[0] > 0.95 and p[1] < 0.05


def test_forward_filter_is_causal():
    rng = np.random.default_rng(5)
    obs = rng.normal(0, 1, (300, 2))
    reset = np.zeros(300, dtype=bool)
    reset[0] = True
    args = (np.full(3, 1 / 3), np.full((3, 3), 1 / 3), rng.normal(0, 1, (3, 2)), np.ones((3, 2)))
    a = regimes.forward_filter(obs, *args, reset)
    obs2 = obs.copy()
    obs2[200:] += 100
    b = regimes.forward_filter(obs2, *args, reset)
    np.testing.assert_allclose(a[:200], b[:200])


def test_bandit_lcb_abstains_on_negative_ev_and_greedy_overfits():
    rng = np.random.default_rng(6)
    rewards = np.where(rng.random((20000, 2)) < 0.54, 0.84, -1.0)  # 54% < 54.35% break-even
    ctx = rng.integers(0, 50, 20000)
    lcb = bandit.learn(ctx, rewards, 50, "lcb")
    greedy = bandit.learn(ctx, rewards, 50, "greedy")
    assert (lcb >= 0).sum() == 0
    assert (greedy >= 0).sum() > 0


def test_page_hinkley_fires_on_decline():
    ph = online.PageHinkley()
    fired = [ph.update(0.84 if i % 2 else -1.0) for i in range(100)]
    fired += [ph.update(-1.0) for _ in range(100)]
    assert not any(fired[:100]) and any(fired[100:])


def test_risk_math():
    assert risk.kelly_fraction(0.5435, 0.84) == pytest.approx(0.0, abs=1e-3)
    assert risk.kelly_fraction(0.52, 0.84) < 0
    assert risk.prob_losing_streak(0.5, 1, 1) == pytest.approx(0.5)
    assert risk.prob_losing_streak(0.5, 2, 3) == pytest.approx(3 / 8)
    n = risk.trades_needed(0.02, metrics.breakeven(0.84))
    assert 3000 < n < 4000


def test_bi5_decoder_round_trip():
    import lzma
    import struct

    from services.otc_quant_lab import leadlag

    blob = lzma.compress(struct.pack(">3I2f", 1500, 115012, 115008, 1.0, 1.0)
                         + struct.pack(">3I2f", 61000, 115020, 115010, 1.0, 1.0), format=lzma.FORMAT_ALONE)
    ticks = leadlag.decode_bi5(blob, 1000.0, 1e5)
    np.testing.assert_allclose(ticks, [[1001.5, 1.1501], [1061.0, 1.15015]])


def test_lead_lag_detects_a_one_bar_copy():
    from services.otc_quant_lab import leadlag

    rng = np.random.default_rng(8)
    real = pd.Series(np.exp(np.cumsum(rng.normal(0, 1e-4, 3000))), index=np.arange(3000) * 120)
    otc = real.shift(1).dropna()  # OTC copies the real close one bar late
    r = leadlag.lead_lag(otc, real)
    assert r["corr_by_lag"][1] > 0.95 and r["rule_hit_rate"] > 0.95


def test_crowd_fade_band_is_frozen():
    from services.otc_quant_lab import crowd

    assert crowd.BAND == (0.30, 0.45)
    s = crowd.fade_signal(np.array([0.5, 0.79, 0.81, 0.94, 0.96, 0.19, 0.06, 0.04]))
    assert s.tolist() == [0, 0, -1, -1, 0, 1, 1, 0]


def test_sequence_windows_stay_inside_one_assets_contiguous_history():
    """Regression for skeptic finding 3: windows gathered after dropping invalid rows wrapped across
    assets and gaps. Rows are now kept; only valid rows are gathered."""
    bars = synthetic_bars(n=300, gap_at=150)
    f = features.build(bars, TF, (1,))
    rows = np.flatnonzero(f.valid.to_numpy())
    offsets = np.arange(-features.SEQ_LEN + 1, 1)
    window = rows[:, None] + offsets[None, :]
    assert (f.asset_id.to_numpy()[window] == f.asset_id.to_numpy()[rows][:, None]).all()
    assert (f.run.to_numpy()[window] == f.run.to_numpy()[rows][:, None]).all()
    seq = features.sequences(f, rows)
    later = f.copy()
    later.loc[later.t > later.t.min() + 200 * TF, features.SEQ_CHANNELS] = 99.0
    early = rows[f.t.to_numpy()[rows] <= f.t.min() + 200 * TF]
    np.testing.assert_array_equal(features.sequences(later, early), features.sequences(f, early))
    assert seq.shape == (len(rows), features.SEQ_LEN, len(features.SEQ_CHANNELS))
    # the old run_lab path (filter to valid rows, then gather) mixes assets: keep that trap visible
    filtered = f[f.valid].reset_index(drop=True)
    r = np.arange(len(filtered))
    w = r[:, None] + offsets[None, :]
    assert (filtered.asset_id.to_numpy()[w] != filtered.asset_id.to_numpy()[r][:, None]).any()


def test_online_thresholds_use_only_previous_days():
    """Regression for skeptic finding 4: the online coverage threshold was the test window's own quantile."""
    rng = np.random.default_rng(10)
    day = np.repeat(np.arange(20), 2000)
    p = rng.uniform(0.4, 0.6, len(day))
    thr = online.causal_thresholds(p, day, 0.1)
    p2 = p.copy()
    p2[day >= 15] = 0.99  # future predictions change; thresholds for days <= 15 must not
    thr2 = online.causal_thresholds(p2, day, 0.1)
    np.testing.assert_array_equal(thr[day <= 15], thr2[day <= 15])
    assert np.isinf(thr[day == 0]).all()


def test_calendar_thirds_and_traded_calibration():
    out = np.array([1] * 10 + [0] * 90)
    days = np.array([0] * 10 + [1] * 45 + [2] * 45)
    s = metrics.trade_summary(out, days)
    assert s["thirds_mean_return"][0] == pytest.approx(0.84)
    c = metrics.traded_calibration(np.full(100, 0.6), np.ones(100, bool), np.array([1] * 60 + [0] * 40))
    assert c["brier"] == pytest.approx(0.24) and c["win_rate"] == pytest.approx(0.6)


def test_model_list_with_deep_names_resolves():
    from services.otc_quant_lab import run_lab

    zoo = run_lab.model_factories("logistic,deep_gru,markov_pat3")
    assert list(zoo) == ["logistic", "deep_gru", "markov_pat3"]


def test_variance_ratio_keeps_lag_and_bh_separate():
    from services.otc_quant_lab import martingale

    f = features.build(synthetic_bars(n=400), TF, (1,))
    rows = np.flatnonzero(f.valid.to_numpy())
    out = martingale.variance_ratio(f, rows, qs=(2, 4))
    assert [o["q"] for o in out] == [2, 4] and all(0 <= o["q_bh"] <= 1 for o in out)


def test_v2_clock_features_are_causal_and_appended():
    assert features.FEATURES_V2[: len(FEATURES)] == FEATURES
    bars = synthetic_bars()
    base = features.build(bars, TF, (1,))
    cut = int(bars.t.min()) + 250 * TF
    mutated = bars.copy()
    later = mutated.t > cut
    mutated.loc[later, ["o", "h", "l", "c"]] *= 1.05
    again = features.build(mutated, TF, (1,))
    rows = base.t <= cut
    np.testing.assert_array_equal(np.nan_to_num(base.loc[rows, features.FEATURES_V2].to_numpy()),
                                  np.nan_to_num(again.loc[rows, features.FEATURES_V2].to_numpy()))
    assert set(base.quad_pos.unique()) <= {0, 1, 2, 3, 4}


def test_burst7_positive_control_triggers_on_about_ten_percent_and_is_not_trend10():
    from services.otc_quant_lab.evals import eval_controls as ec

    bars = synthetic_bars(n=6000, seed=3)[lambda d: d.asset == "EURUSD-OTC"]
    out = ec.randomise(bars, 1, 0.57, "burst7").sort_values("t")
    r = np.diff(np.log(out.c.to_numpy()))
    s = pd.Series(r)
    move = s.rolling(7).sum().shift(1)
    sd = s.rolling(30).std(ddof=0).shift(1) * np.sqrt(7)
    trig = (move.abs() > 1.645 * sd) & (s.abs() > 0)
    share = trig[40:].mean()
    cont = (np.sign(s[trig]) == np.sign(move[trig])).mean()
    assert 0.05 < share < 0.16 and 0.53 < cont < 0.62
    assert ec.FORMS["burst7"] != ec.FORMS["trend10"]


def test_second_labels_use_last_close_at_or_before_with_staleness_limit():
    from services.otc_quant_lab import short_expiry

    frame = pd.DataFrame({"asset": ["A", "A"], "t": [0, 120]})
    seconds = pd.DataFrame({"asset": "A", "t": [120, 121, 179, 180, 240, 300], "c": [1.0, 1.1, 1.2, 1.0, 1.3, 1.3]})
    lab = short_expiry.second_labels(frame, seconds, delay=0, expiry=60)
    assert lab[0] == features.TIE  # entry close at 120 = 1.0, expiry close at 180 = 1.0
    assert lab[1] == features.TIE  # entry 240 -> 1.3, expiry 300 -> 1.3
    lab2 = short_expiry.second_labels(frame, seconds, delay=1, expiry=60)
    assert lab2[0] == features.DOWN  # 1.1 at 121 -> 1.0 at 180
    stale = short_expiry.second_labels(frame, seconds.iloc[:2], delay=0, expiry=60)
    assert (stale == features.UNKNOWN).all()


def test_controls_rejudge_p2_at_main_study_k():
    from types import SimpleNamespace

    from services.otc_quant_lab.evals import eval_controls as ec

    checks = {c: True for c in ("P1_trades_days", "P2_bonferroni_wilson", "P3_mean_and_bootstrap", "P4_thirds",
                                "P5_assets", "P6_pbo", "P7_calibration")}
    row = {"kind": "positive", "seed": 0, "winner": "x", "pass": True, "checks": {**checks, "pass": True},
           "final_wins": 560, "final_losses": 440, "breakeven": 0.5435, "final_trades": 1000, "final_win_rate": 0.56}
    v = ec.summarise([row], SimpleNamespace(models="m", horizons="1", judge_k=432))
    assert v["pass_at_judge_k"]["positive"] == [False]  # 56% on 1,000 is not enough at K = 432
    row2 = {**row, "final_wins": 5800, "final_losses": 4200, "final_trades": 10000, "final_win_rate": 0.58}
    assert ec.summarise([row2], SimpleNamespace(models="m", horizons="1", judge_k=432))["pass_at_judge_k"]["positive"] == [True]


def test_short_expiry_test_window_is_purged_and_embargoed():
    from services.otc_quant_lab import short_expiry

    lookback_s = features.LOOKBACK * 120
    longest_expiry_s = max(short_expiry.EXPIRIES)
    t = np.sort(np.random.default_rng(12).uniform(0, 20 * 86400, 5000))
    spans = short_expiry.split_spans(t)
    inside = {k: t[(t > lo) & (t <= hi)] for k, (lo, hi) in spans.items()}
    gap = inside["test"].min() - inside["inner"].max()
    assert gap >= lookback_s + longest_expiry_s + 86400  # fails if the split stops applying the gap
    assert inside["train"].max() < inside["inner"].min()
