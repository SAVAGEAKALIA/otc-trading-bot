"""Explicit translation from legacy OTC request objects to platform records."""

from datetime import datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform.domain.orders import BinaryDirection
from trading_platform.domain.time import require_utc
from trading_platform.strategies.otc.shadow import OTCCandidate

from .models import TradeRequest


class LegacyTradeRequestAdapter:
    @staticmethod
    def to_otc_candidate(
        request: TradeRequest,
        *,
        stake: Decimal,
        payout_ratio: Decimal,
        estimated_win_probability: Decimal | None,
        decision_at: datetime,
        signal_id: UUID | None = None,
    ) -> OTCCandidate:
        require_utc(decision_at, "decision_at")
        direction = BinaryDirection(request.signal.direction.lower())
        stable_id = signal_id or uuid5(
            NAMESPACE_URL,
            ":".join(
                (
                    "legacy-otc",
                    request.source,
                    request.signal.asset.upper(),
                    direction.value,
                    str(request.signal.duration),
                    decision_at.isoformat(),
                )
            ),
        )
        return OTCCandidate(
            signal_id=stable_id,
            asset=request.signal.asset,
            direction=direction,
            duration_minutes=request.signal.duration,
            stake=stake,
            payout_ratio=payout_ratio,
            estimated_win_probability=estimated_win_probability,
            confidence=Decimal(str(request.ai_confidence)),
            decision_at=decision_at,
            strategy_id=request.strategy_used or f"legacy-{request.source}",
            source=request.source,
            calibration_version=request.calibration_version,
            martingale_step=request.martingale_step,
        )
