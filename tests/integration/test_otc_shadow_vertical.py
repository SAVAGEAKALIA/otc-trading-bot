from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.orders import BinaryDirection, OrderStatus
from trading_platform.risk.engine import RiskEngine
from trading_platform.risk.policies import RiskLimits
from trading_platform.risk.state import RiskState
from trading_platform.storage.models import metadata
from trading_platform.storage.repository import LedgerRepository
from trading_platform.strategies.otc.shadow import OTCCandidate, OTCShadowService
from tests.calibration_fixtures import calibration_provenance


NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
INSTRUMENT = InstrumentId(
    "iqoption", ProductType.BINARY_OPTION, "EURUSD-OTC", "USD"
)


def candidate(**overrides) -> OTCCandidate:
    values = {
        "signal_id": UUID("00000000-0000-0000-0000-000000000010"),
        "asset": "eurusd-op",
        "direction": BinaryDirection.CALL,
        "duration_minutes": 2,
        "stake": Decimal("5"),
        "payout_ratio": Decimal("0.84"),
        "estimated_win_probability": Decimal("0.60"),
        "confidence": Decimal("0.75"),
        "decision_at": NOW - timedelta(seconds=1),
        "strategy_id": "legacy-scanner-parity",
        "source": "scanner",
        "calibration_version": "cal-v1",
    }
    values.update(overrides)
    return OTCCandidate(**values)


def risk_engine() -> RiskEngine:
    return RiskEngine(
        RiskLimits(
            allowed_instruments=frozenset({INSTRUMENT}),
            max_signal_age=timedelta(seconds=10),
            max_state_age=timedelta(seconds=5),
            max_market_data_age=timedelta(seconds=5),
            max_order_notional=Decimal("10"),
            max_instrument_exposure=Decimal("10"),
            max_total_exposure=Decimal("10"),
            max_leverage=Decimal("1"),
            max_drawdown_fraction=Decimal("0.10"),
            max_open_orders=1,
            min_liquidation_buffer_fraction=Decimal("0"),
        )
    )


def risk_state() -> RiskState:
    return RiskState(
        environment=TradingEnvironment.SHADOW,
        as_of=NOW,
        equity=Decimal("100"),
        peak_equity=Decimal("100"),
        total_abs_exposure=Decimal("0"),
        instrument_exposures={},
        open_order_count=0,
        seen_signal_ids=frozenset(),
        market_data_as_of={INSTRUMENT: NOW},
    )


@pytest.fixture
def repository(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'otc-shadow.db'}")
    metadata.create_all(engine)
    result = LedgerRepository(engine)
    result.register_calibration_provenance(
        calibration_provenance(
            calibration_id="cal-v1",
            model_version="cal-v1",
        )
    )
    return result


@pytest.mark.asyncio
async def test_legacy_otc_candidate_maps_to_durable_shadow_order(repository) -> None:
    result = await OTCShadowService(repository, risk_engine()).evaluate(
        candidate(), risk_state(), now=NOW
    )

    assert result.signal.instrument == INSTRUMENT
    assert result.signal.action.value == "call"
    assert result.expectancy == Decimal("0.1040")
    assert result.risk_decision.is_approved
    assert result.order is not None
    assert result.order.status is OrderStatus.ACKNOWLEDGED
    assert result.order.broker_order_id.startswith("SHADOW-")
    assert result.order.intent.binary_terms.direction is BinaryDirection.CALL
    assert result.order.intent.binary_terms.payout_ratio == Decimal("0.84")
    assert result.order.intent.binary_terms.expires_at == NOW - timedelta(seconds=1) + timedelta(minutes=2)
    assert repository.signal_decision_count() == 1


@pytest.mark.asyncio
async def test_uncalibrated_or_negative_expectancy_signal_is_recorded_but_not_ordered(repository) -> None:
    uncalibrated = await OTCShadowService(repository, risk_engine()).evaluate(
        candidate(estimated_win_probability=None), risk_state(), now=NOW
    )

    assert not uncalibrated.risk_decision.is_approved
    assert "calibrated win probability is missing" in uncalibrated.risk_decision.reasons
    assert uncalibrated.order is None
    assert repository.order_count() == 0
    assert repository.signal_decision_count() == 1


@pytest.mark.asyncio
async def test_martingale_is_rejected_by_migrated_path(repository) -> None:
    result = await OTCShadowService(repository, risk_engine()).evaluate(
        candidate(martingale_step=1), risk_state(), now=NOW
    )
    assert "martingale is disabled in the migrated OTC path" in result.risk_decision.reasons
    assert result.order is None


@pytest.mark.asyncio
async def test_unregistered_calibration_cannot_authorize_shadow_order(repository) -> None:
    result = await OTCShadowService(repository, risk_engine()).evaluate(
        candidate(calibration_version="unknown-calibration"),
        risk_state(),
        now=NOW,
    )

    assert "calibration provenance is not registered" in result.risk_decision.reasons
    assert result.order is None


@pytest.mark.asyncio
async def test_unapproved_calibration_cannot_authorize_shadow_order(repository) -> None:
    repository.register_calibration_provenance(
        calibration_provenance(
            calibration_id="research-only-cal",
            model_version="research-only-model",
            offline_deployment_approved=False,
        )
    )

    result = await OTCShadowService(repository, risk_engine()).evaluate(
        candidate(calibration_version="research-only-cal"),
        risk_state(),
        now=NOW,
    )

    assert (
        "calibration provenance is not deployment approved"
        in result.risk_decision.reasons
    )
    assert result.order is None


@pytest.mark.asyncio
async def test_same_fixture_replays_idempotently(repository) -> None:
    service = OTCShadowService(repository, risk_engine())
    fixed = candidate()

    first = await service.evaluate(fixed, risk_state(), now=NOW)
    second = await service.evaluate(fixed, risk_state(), now=NOW)

    assert first.risk_decision == second.risk_decision
    assert first.order == second.order
    assert repository.order_count() == 1
    assert repository.signal_decision_count() == 1
