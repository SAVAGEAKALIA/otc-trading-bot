from decimal import Decimal

import pytest

from trading_platform.brokers.bybit.positions import BybitPositionRecord, to_projection
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.orders import OrderSide


def test_projection_preserves_hedge_leg_identity():
    record = BybitPositionRecord(
        instrument=InstrumentId("BYBIT", ProductType.LINEAR_PERPETUAL, "BTCUSDT", "USDT"),
        position_index=1, side=OrderSide.BUY, signed_quantity=Decimal("1"),
        average_entry_price=Decimal("100"), mark_price=Decimal("101"),
        position_value=Decimal("101"), unrealized_pnl=Decimal("1"),
        leverage=Decimal("2"), liquidation_price=None,
        initial_margin=None, maintenance_margin=None,
    )
    assert to_projection(record).position_idx == 1


def test_projection_rejects_unknown_leverage():
    record = BybitPositionRecord(
        instrument=InstrumentId("BYBIT", ProductType.LINEAR_PERPETUAL, "BTCUSDT", "USDT"),
        position_index=2, side=OrderSide.SELL, signed_quantity=Decimal("-1"),
        average_entry_price=Decimal("100"), mark_price=Decimal("101"),
        position_value=Decimal("101"), unrealized_pnl=Decimal("1"),
        leverage=None, liquidation_price=None,
        initial_margin=None, maintenance_margin=None,
    )
    with pytest.raises(ValueError, match="unknown leverage"):
        to_projection(record)
