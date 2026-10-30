import numpy as np
import pandas as pd
import pytest

from trading_platform.research.validation.edge_audit import (
    audit_candle_rules,
    audit_trade_log,
    breakeven_win_rate,
    direction_frame,
    render_markdown,
    wilson_interval,
)

PAYOUT = 0.85


def _candles(signs: np.ndarray, *, timeframe: int = 120, asset: str = "EURUSD-OTC") -> pd.DataFrame:
    start = pd.Timestamp("2026-08-01", tz="UTC")
    opens = np.full(len(signs), 1.0)
    return pd.DataFrame(
        {
            "asset": asset,
            "timeframe": timeframe,
            "timestamp": [start + pd.Timedelta(seconds=timeframe * i) for i in range(len(signs))],
            "open": opens,
            "close": opens + signs * 0.001,
        }
    )


def _by_name(results):
    return {r.name: r for r in results}


def test_breakeven_matches_payout_arithmetic():
    assert breakeven_win_rate(0.85) == pytest.approx(0.540540, abs=1e-6)
    assert breakeven_win_rate(1.0) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        breakeven_win_rate(0)


def test_wilson_interval_known_value_and_edges():
    low, high = wilson_interval(133, 250)
    assert (low, high) == pytest.approx((0.47014, 0.59287), abs=1e-4)
    assert wilson_interval(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError):
        wilson_interval(5, 4)


def test_random_walk_clears_no_rule():
    rng = np.random.default_rng(7)
    frame = direction_frame(_candles(rng.choice([-1.0, 1.0], size=40_000)), 120)
    results = audit_candle_rules(frame, PAYOUT)
    assert not any(r.clears_breakeven for r in results)
    assert all(abs(r.win_rate - 0.5) < 0.02 for r in results if r.trades > 1000)


def test_planted_mean_reversion_is_detected_as_edge():
    rng = np.random.default_rng(11)
    signs = [1.0]
    for _ in range(40_000):
        signs.append(-signs[-1] if rng.random() < 0.62 else signs[-1])
    results = _by_name(audit_candle_rules(direction_frame(_candles(np.array(signs)), 120), PAYOUT))
    assert results["lag1_reversal"].clears_breakeven
    assert results["lag1_reversal"].win_rate == pytest.approx(0.62, abs=0.01)
    assert not results["lag1_continuation"].clears_breakeven
    assert "EDGE FOUND" in render_markdown("planted", results.values())


def test_gaps_in_lags_or_outcome_never_create_samples():
    candles = _candles(np.array([1.0, -1.0, 1.0, 1.0, -1.0, 1.0, -1.0]))
    # Missing slot before candle 1 and before candle 6.
    candles.loc[1:, "timestamp"] += pd.Timedelta(seconds=120)
    candles.loc[6:, "timestamp"] += pd.Timedelta(seconds=120)
    frame = direction_frame(candles, 120)
    # Candle 2 is excluded only by its lag-2 gap; candle 5 only by its outcome gap.
    assert len(frame) == 2
    assert frame[["s2", "s1", "s0", "y"]].values.tolist() == [
        [-1.0, 1.0, 1.0, -1.0],
        [1.0, 1.0, -1.0, 1.0],
    ]


def test_doji_candles_are_neither_signal_nor_outcome():
    frame = direction_frame(_candles(np.array([1.0, -1.0, 1.0, 1.0, 0.0, -1.0, 1.0, -1.0, 1.0])), 120)
    # Every row touching the doji (as s0, s1, s2 or y) is dropped.
    assert frame[["s2", "s1", "s0", "y"]].values.tolist() == [
        [1.0, -1.0, 1.0, 1.0],
        [-1.0, 1.0, -1.0, 1.0],
    ]


def test_assets_are_not_chained_together():
    a = _candles(np.array([1.0, 1.0, 1.0]), asset="A")
    b = _candles(np.array([-1.0, -1.0, -1.0]), asset="B")
    # B starts exactly where A ends, so chaining across assets would yield rows.
    b["timestamp"] += pd.Timedelta(seconds=3 * 120)
    assert direction_frame(pd.concat([a, b]), 120).empty


def test_trade_log_uses_logged_payout_and_skips_ties():
    rows = [{"result": "win", "payout_rate": 0.86}] * 133 + [{"result": "lose", "payout_rate": 0.83}] * 117
    rows += [{"result": "tie"}, {"result": None}]
    result = audit_trade_log(rows, default_payout=0.85)
    assert result.trades == 250 and result.wins == 133
    assert result.breakeven == pytest.approx(1 / (1 + (0.86 * 133 + 0.83 * 117) / 250))
    assert not result.clears_breakeven


def test_small_lucky_sample_does_not_clear_on_point_estimate():
    rows = [{"result": "win"}] * 60 + [{"result": "lose"}] * 40
    result = audit_trade_log(rows, default_payout=0.85)
    assert result.win_rate == 0.6 > result.breakeven
    assert result.ci_low < result.breakeven
    assert not result.clears_breakeven
