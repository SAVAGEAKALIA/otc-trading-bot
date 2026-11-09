"""Opt-in runtime mirror into the new shadow-only platform workflow."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine

from trading_platform.brokers.iqoption.history import IQOptionClosedOptionsHistory
from trading_platform.brokers.iqoption.settlement import IQOptionSettlementGateway
from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.execution.binary_settlement import BinarySettlementReconciler
from trading_platform.risk.engine import RiskEngine
from trading_platform.risk.policies import RiskLimits
from trading_platform.risk.state import RiskState
from trading_platform.storage.models import metadata
from trading_platform.storage.repository import LedgerRepository
from trading_platform.strategies.otc.shadow import OTCShadowPolicy, OTCShadowService

from .models import TradeRequest
from .platform_compat import LegacyTradeRequestAdapter


class PlatformShadowMirror:
    def __init__(self, database_url: str, config: dict, broker_api=None) -> None:
        if not database_url.strip():
            raise ValueError("PLATFORM_DATABASE_URL is required when shadow mirroring is enabled")
        self.engine = create_engine(database_url, pool_pre_ping=True)
        if self.engine.dialect.name == "sqlite":
            metadata.create_all(self.engine)
        self.repository = LedgerRepository(self.engine)
        self.history = (
            IQOptionClosedOptionsHistory(
                broker_api,
                request_timeout=float(config.get("platform_history_timeout", 5.0)),
                page_size=int(config.get("platform_history_page_size", 100)),
                max_pages=int(config.get("platform_history_max_pages", 5)),
            )
            if broker_api is not None
            else None
        )
        self.max_stake = Decimal(str(config.get("platform_shadow_max_stake", 50)))
        self.min_payout = Decimal(str(config.get("platform_shadow_min_payout", 0.70)))
        self.min_expectancy = Decimal(
            str(config.get("platform_shadow_min_expectancy", 0.0))
        )
        self._peak_equity = Decimal("0")

    async def mirror(
        self,
        request: TradeRequest,
        *,
        stake: Decimal,
        payout_ratio: Decimal,
        balance: Decimal,
        active_exposure: Decimal,
        open_order_count: int,
    ):
        candidate = LegacyTradeRequestAdapter.to_otc_candidate(
            request,
            stake=stake,
            payout_ratio=payout_ratio,
            estimated_win_probability=(
                Decimal(str(request.calibrated_win_probability))
                if request.calibrated_win_probability is not None
                else None
            ),
            decision_at=request.platform_decision_at,
        )
        instrument = InstrumentId(
            "iqoption", ProductType.BINARY_OPTION, candidate.normalized_asset, "USD"
        )
        evaluated_at = datetime.now(UTC)
        self._peak_equity = max(self._peak_equity, balance)
        limits = RiskLimits(
            allowed_instruments=frozenset({instrument}),
            max_signal_age=timedelta(seconds=60),
            max_state_age=timedelta(seconds=5),
            max_market_data_age=timedelta(seconds=5),
            max_order_notional=self.max_stake,
            max_instrument_exposure=self.max_stake,
            max_total_exposure=self.max_stake,
            max_leverage=Decimal("1"),
            max_drawdown_fraction=Decimal("0.10"),
            max_open_orders=max(1, open_order_count + 1),
            min_liquidation_buffer_fraction=Decimal("0"),
        )
        state = RiskState(
            environment=TradingEnvironment.SHADOW,
            as_of=evaluated_at,
            equity=balance,
            peak_equity=max(self._peak_equity, balance),
            total_abs_exposure=active_exposure,
            instrument_exposures={},
            open_order_count=open_order_count,
            seen_signal_ids=frozenset(),
            market_data_as_of={instrument: request.platform_decision_at},
        )
        service = OTCShadowService(
            self.repository,
            RiskEngine(limits),
            OTCShadowPolicy(
                min_payout_ratio=self.min_payout,
                min_expectancy=self.min_expectancy,
            ),
        )
        return await service.evaluate(
            candidate,
            state,
            now=evaluated_at,
            legacy_disposition="legacy_would_submit",
        )

    def bind_broker_order_id(self, result, broker_order_id: object):
        """Bind the accepted legacy broker ID to the shadow ledger order."""
        if result.order is None:
            raise ValueError("cannot bind broker ID without a shadow order")
        return self.repository.bind_broker_order_id(
            result.order.client_order_id,
            str(broker_order_id),
            expected_broker_order_id=result.order.broker_order_id,
        )

    async def reconcile_settlements(self, now: datetime):
        """Record broker-confirmed settlements for bound shadow orders."""
        if self.history is None:
            return []
        return await BinarySettlementReconciler(
            self.repository,
            IQOptionSettlementGateway(self.history),
            TradingEnvironment.SHADOW,
        ).reconcile_due(now)

    def close(self) -> None:
        self.engine.dispose()
