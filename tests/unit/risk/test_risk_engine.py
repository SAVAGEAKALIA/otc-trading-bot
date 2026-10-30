from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.signals import SignalAction, SignalProposal
from trading_platform.risk.engine import RiskEngine, RiskRequest
from trading_platform.risk.policies import RiskLimits
from trading_platform.risk.state import RiskState


NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
BTC = InstrumentId("bybit", ProductType.LINEAR_PERPETUAL, "BTCUSDT", "USDT")


def signal(
    *,
    instrument: InstrumentId = BTC,
    environment: TradingEnvironment = TradingEnvironment.TESTNET,
    decision_at: datetime = NOW - timedelta(seconds=1),
    action: SignalAction = SignalAction.OPEN_LONG,
) -> SignalProposal:
    return SignalProposal(
        strategy_id="trend-v1",
        instrument=instrument,
        environment=environment,
        action=action,
        confidence=Decimal("0.7"),
        decision_at=decision_at,
        expires_at=decision_at + timedelta(minutes=1),
    )


def limits(**overrides) -> RiskLimits:
    values = {
        "allowed_instruments": frozenset({BTC}),
        "max_signal_age": timedelta(seconds=10),
        "max_state_age": timedelta(seconds=5),
        "max_market_data_age": timedelta(seconds=5),
        "max_order_notional": Decimal("1000"),
        "max_instrument_exposure": Decimal("2000"),
        "max_total_exposure": Decimal("3000"),
        "max_leverage": Decimal("3"),
        "max_drawdown_fraction": Decimal("0.10"),
        "max_open_orders": 3,
        "min_liquidation_buffer_fraction": Decimal("0.15"),
    }
    values.update(overrides)
    return RiskLimits(**values)


def state(**overrides) -> RiskState:
    values = {
        "environment": TradingEnvironment.TESTNET,
        "as_of": NOW,
        "equity": Decimal("1000"),
        "peak_equity": Decimal("1050"),
        "total_abs_exposure": Decimal("500"),
        "instrument_exposures": {BTC: Decimal("500")},
        "open_order_count": 1,
        "seen_signal_ids": frozenset(),
        "market_data_as_of": {BTC: NOW - timedelta(seconds=1)},
        "kill_switch_active": False,
    }
    values.update(overrides)
    return RiskState(**values)


def request(proposal: SignalProposal | None = None, **overrides) -> RiskRequest:
    values = {
        "signal": proposal or signal(),
        "quantity": Decimal("0.01"),
        "reference_price": Decimal("50000"),
        "requested_leverage": Decimal("1"),
        "liquidation_buffer_fraction": None,
    }
    values.update(overrides)
    return RiskRequest(**values)


def test_approves_at_exact_boundaries_and_records_limit_snapshot() -> None:
    engine = RiskEngine(
        limits(
            max_order_notional=Decimal("500"),
            max_instrument_exposure=Decimal("1000"),
            max_total_exposure=Decimal("1000"),
        )
    )

    proposal = signal()
    decision = engine.evaluate(request(proposal), state(), now=NOW)

    assert decision.is_approved
    assert decision.signal_id == proposal.signal_id
    assert decision.limits_snapshot["max_order_notional"] == "500"


@pytest.mark.parametrize(
    ("state_override", "reason"),
    [
        ({"kill_switch_active": True}, "kill switch is active"),
        ({"open_order_count": 3}, "open order limit reached"),
        ({"equity": Decimal("900"), "peak_equity": Decimal("1000")}, "drawdown limit reached"),
    ],
)
def test_state_limits_reject(state_override, reason) -> None:
    decision = RiskEngine(limits()).evaluate(request(), state(**state_override), now=NOW)
    assert not decision.is_approved
    assert reason in decision.reasons


def test_kill_switch_has_highest_precedence() -> None:
    stale = signal(decision_at=NOW - timedelta(hours=1))
    decision = RiskEngine(limits()).evaluate(
        request(stale), state(kill_switch_active=True), now=NOW
    )
    assert decision.reasons[0] == "kill switch is active"


def test_duplicate_stale_expired_and_future_signals_reject() -> None:
    proposal = signal(decision_at=NOW - timedelta(seconds=20))
    current = state(seen_signal_ids=frozenset({proposal.signal_id}))
    decision = RiskEngine(limits()).evaluate(request(proposal), current, now=NOW)
    assert "signal has already been evaluated" in decision.reasons
    assert "signal is stale" in decision.reasons

    future = signal(decision_at=NOW + timedelta(seconds=1))
    future_decision = RiskEngine(limits()).evaluate(request(future), state(), now=NOW)
    assert "signal decision time is in the future" in future_decision.reasons


def test_missing_or_stale_market_data_rejects() -> None:
    missing = RiskEngine(limits()).evaluate(
        request(), state(market_data_as_of={}), now=NOW
    )
    assert "market data timestamp is missing" in missing.reasons

    stale = RiskEngine(limits()).evaluate(
        request(),
        state(market_data_as_of={BTC: NOW - timedelta(seconds=6)}),
        now=NOW,
    )
    assert "market data is stale" in stale.reasons


def test_allowed_instrument_environment_and_abstain_reject() -> None:
    other = InstrumentId("bybit", ProductType.SPOT, "ETHUSDT", "USDT")
    denied = RiskEngine(limits()).evaluate(request(signal(instrument=other)), state(), now=NOW)
    assert "instrument is not allowed" in denied.reasons

    mismatch = RiskEngine(limits()).evaluate(
        request(signal(environment=TradingEnvironment.PAPER)), state(), now=NOW
    )
    assert "signal and risk state environments differ" in mismatch.reasons

    abstain = signal(action=SignalAction.ABSTAIN)
    abstained = RiskEngine(limits()).evaluate(request(abstain), state(), now=NOW)
    assert "abstain signals cannot be traded" in abstained.reasons


@pytest.mark.parametrize(
    ("request_override", "state_override", "reason"),
    [
        ({"quantity": Decimal("0.021")}, {}, "order notional limit exceeded"),
        ({"quantity": Decimal("0.031")}, {}, "instrument exposure limit exceeded"),
        ({"quantity": Decimal("0.051")}, {}, "total exposure limit exceeded"),
        ({"requested_leverage": Decimal("3.1")}, {}, "requested leverage limit exceeded"),
        ({}, {"total_abs_exposure": Decimal("2600")}, "portfolio leverage limit exceeded"),
    ],
)
def test_notional_exposure_and_leverage_limits(request_override, state_override, reason) -> None:
    custom = limits(
        max_order_notional=Decimal("1000"),
        max_instrument_exposure=Decimal("2000"),
        max_total_exposure=Decimal("3000"),
    )
    decision = RiskEngine(custom).evaluate(
        request(**request_override), state(**state_override), now=NOW
    )
    assert reason in decision.reasons


def test_leveraged_perpetual_requires_liquidation_buffer() -> None:
    engine = RiskEngine(limits())
    missing = engine.evaluate(
        request(requested_leverage=Decimal("2")), state(), now=NOW
    )
    assert "liquidation buffer is missing" in missing.reasons

    low = engine.evaluate(
        request(
            requested_leverage=Decimal("2"),
            liquidation_buffer_fraction=Decimal("0.14"),
        ),
        state(),
        now=NOW,
    )
    assert "liquidation buffer is below minimum" in low.reasons


def test_invalid_or_missing_state_fails_during_construction() -> None:
    with pytest.raises(ValueError):
        state(equity=Decimal("0"))
    with pytest.raises(ValueError):
        request(reference_price=Decimal("0"))


@given(
    quantity=st.decimals(
        min_value=Decimal("0.0001"),
        max_value=Decimal("0.0300"),
        places=4,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_order_notional_boundary_is_stable(quantity: Decimal) -> None:
    engine = RiskEngine(
        limits(
            max_order_notional=Decimal("500"),
            max_instrument_exposure=Decimal("10000"),
            max_total_exposure=Decimal("10000"),
            max_leverage=Decimal("20"),
        )
    )
    decision = engine.evaluate(request(quantity=quantity), state(), now=NOW)
    exceeded = quantity * Decimal("50000") > Decimal("500")
    assert ("order notional limit exceeded" in decision.reasons) is exceeded
