from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.orders import BinaryDirection
from trading_platform.risk.engine import RiskEngine
from trading_platform.risk.policies import RiskLimits
from trading_platform.risk.state import RiskState
from trading_platform.storage.models import metadata
from trading_platform.storage.repository import LedgerRepository
from trading_platform.strategies.otc.shadow import OTCCandidate, OTCShadowService
from tests.calibration_fixtures import calibration_provenance


NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
INSTRUMENT = InstrumentId("iqoption", ProductType.BINARY_OPTION, "EURUSD-OTC", "USD")


@pytest.mark.asyncio
async def test_lists_typed_signal_decisions_in_stable_order(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'decisions.db'}")
    metadata.create_all(engine)
    repository = LedgerRepository(engine)
    repository.register_calibration_provenance(
        calibration_provenance(calibration_id="cal-v1", model_version="cal-v1")
    )
    limits = RiskLimits(
        allowed_instruments=frozenset({INSTRUMENT}),
        max_signal_age=timedelta(seconds=10),
        max_state_age=timedelta(seconds=5),
        max_market_data_age=timedelta(seconds=5),
        max_order_notional=Decimal("10"),
        max_instrument_exposure=Decimal("10"),
        max_total_exposure=Decimal("10"),
        max_leverage=Decimal("1"),
        max_drawdown_fraction=Decimal("0.1"),
        max_open_orders=1,
        min_liquidation_buffer_fraction=Decimal("0"),
    )
    state = RiskState(
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
    service = OTCShadowService(repository, RiskEngine(limits))
    for suffix, probability in ((2, None), (1, Decimal("0.60"))):
        await service.evaluate(
            OTCCandidate(
                signal_id=UUID(f"00000000-0000-0000-0000-{suffix:012d}"),
                asset="EURUSD-OTC",
                direction=BinaryDirection.CALL,
                duration_minutes=2,
                stake=Decimal("5"),
                payout_ratio=Decimal("0.84"),
                estimated_win_probability=probability,
                confidence=Decimal("0.75"),
                decision_at=NOW - timedelta(seconds=1),
                strategy_id="catboost-gate",
                source="scanner",
                calibration_version="cal-v1" if probability is not None else None,
            ),
            state,
            now=NOW,
            legacy_disposition="legacy_would_submit",
        )

    records = repository.list_signal_decisions()

    assert [record.signal_id for record in records] == [
        UUID("00000000-0000-0000-0000-000000000001"),
        UUID("00000000-0000-0000-0000-000000000002"),
    ]
    assert records[0].approved is True
    assert records[0].source == "scanner"
    assert records[0].strategy_id == "catboost-gate"
    assert records[0].calibration_version == "cal-v1"
    assert records[0].legacy_disposition == "legacy_would_submit"
    assert records[1].reasons == ("calibrated win probability is missing",)
