from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_platform.research.crypto import (
    CryptoBar,
    CryptoCostModel,
    assess_crypto_candidate,
    CryptoResearchEngine,
    PointInTimeUniverse,
    generate_breakout_signals,
    generate_mean_reversion_signals,
    generate_momentum_signals,
    evaluate_parameter_surface,
)


START = datetime(2026, 1, 1, tzinfo=UTC)


def bars(*closes):
    result = []
    for index, close in enumerate(closes):
        value = Decimal(str(close))
        result.append(
            CryptoBar(
                "BTCUSDT",
                START + timedelta(hours=index),
                value,
                value,
                value,
                value,
                Decimal("10"),
            )
        )
    return result


def test_baselines_are_causal_and_directional():
    values = bars(100, 110, 121, 115, 105)

    momentum = generate_momentum_signals(values, lookback=1, threshold=Decimal("0.05"))
    reversion = generate_mean_reversion_signals(values, lookback=1, threshold=Decimal("0.05"))
    breakout = generate_breakout_signals(values, lookback=2)

    assert momentum[0].decision_at == values[1].observed_at
    assert momentum[0].direction == "long"
    assert reversion[0].direction == "short"
    assert breakout[0].direction == "long"


def test_point_in_time_universe_rejects_symbols_not_yet_listed():
    values = bars(100, 110, 121)
    universe = [PointInTimeUniverse(START + timedelta(hours=1), ("ETHUSDT",))]
    signals = generate_momentum_signals(values, lookback=1)

    report = CryptoResearchEngine().run(
        bars=values, signals=signals, universe=universe, starting_equity=Decimal("1000")
    )

    assert report["accepted_signals"] == 0
    assert report["rejected_signals"] == len(signals)


def test_costs_funding_and_notional_limits_are_explicit():
    values = bars(100, 110, 121, 133)
    signals = generate_momentum_signals(values, lookback=1)
    report = CryptoResearchEngine(
        CryptoCostModel(
            taker_fee_bps=Decimal("10"),
            slippage_bps=Decimal("5"),
            funding_bps_per_bar=Decimal("2"),
            leverage=Decimal("2"),
            maximum_gross_notional=Decimal("1000"),
        )
    ).run(
        bars=values,
        signals=signals,
        universe=[PointInTimeUniverse(START, ("BTCUSDT",))],
        starting_equity=Decimal("10000"),
    )

    assert report["accepted_signals"] == 1
    assert report["costs"] > Decimal("0")
    assert report["net_pnl"] < report["gross_pnl"]


def test_crypto_research_rejects_future_or_duplicate_bar_ordering():
    values = bars(100, 110)
    with pytest.raises(ValueError, match="chronological"):
        generate_momentum_signals([values[1], values[0]])

    signals = generate_momentum_signals(values)
    with pytest.raises(ValueError, match="duplicate"):
        CryptoResearchEngine().run(
            bars=values,
            signals=(*signals, *signals),
            universe=[PointInTimeUniverse(START, ("BTCUSDT",))],
            starting_equity=Decimal("1000"),
        )


def test_parameter_surface_is_deterministic_and_keeps_all_parameters():
    values = bars(100, 110, 121, 115, 130)
    surface = evaluate_parameter_surface(
        bars=values,
        universe=[PointInTimeUniverse(START, ("BTCUSDT",))],
        starting_equity=Decimal("1000"),
        parameter_values=(1, 2),
    )

    assert [item["parameter"] for item in surface] == [1, 2]
    assert all("net_pnl" in item and "costs" in item for item in surface)


def test_candidate_gate_retains_negative_results_and_fails_closed():
    baseline = (
        {"accepted_signals": 20, "net_pnl": Decimal("10")},
        {"accepted_signals": 20, "net_pnl": Decimal("11")},
        {"accepted_signals": 20, "net_pnl": Decimal("12")},
    )
    adverse = ({"accepted_signals": 20, "net_pnl": Decimal("-1")},)

    assessment = assess_crypto_candidate(
        hypothesis_id="momentum-v1",
        baseline_reports=baseline,
        adverse_reports=adverse,
        minimum_accepted_signals=50,
    )

    assert assessment.passed is False
    assert "candidate does not survive adverse costs" in assessment.reasons
    assert assessment.adverse_reports[0]["net_pnl"] == Decimal("-1")
