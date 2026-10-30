from decimal import Decimal

import pytest

from trading_platform.brokers.bybit.positions import normalize_position_page
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.orders import OrderSide


BTC = InstrumentId("BYBIT", ProductType.LINEAR_PERPETUAL, "BTCUSDT", "USDT")


def position(symbol="BTCUSDT", side="Buy", index=1, size="0.25"):
    return {
        "symbol": symbol,
        "side": side,
        "size": size,
        "positionIdx": index,
        "avgPrice": "60000",
        "markPrice": "61000",
        "positionValue": "15250",
        "unrealisedPnl": "250",
        "leverage": "3",
        "liqPrice": "45000",
        "positionIM": "5000",
        "positionMM": "75",
    }


def response(items=None):
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "category": "linear",
            "nextPageCursor": "next",
            "list": items if items is not None else [position()],
        },
        "time": 1_800_000_000_000,
    }


def test_normalizes_hedge_legs_without_collapsing_instrument_identity() -> None:
    payload = response(
        [position(side="Buy", index=1), position(side="Sell", index=2, size="0.10")]
    )

    page = normalize_position_page(
        payload, expected_category="linear", instruments={"BTCUSDT": BTC}
    )

    long_leg, short_leg = page.positions
    assert long_leg.position_index == 1
    assert long_leg.side is OrderSide.BUY
    assert long_leg.signed_quantity == Decimal("0.25")
    assert short_leg.position_index == 2
    assert short_leg.side is OrderSide.SELL
    assert short_leg.signed_quantity == Decimal("-0.10")
    assert page.next_cursor == "next"


def test_skips_zero_positions_but_preserves_portfolio_margin_unknowns() -> None:
    active = position(index=0)
    active["leverage"] = ""
    active["liqPrice"] = ""
    active["positionIM"] = "0"
    payload = response([position(side="", index=0, size="0"), active])

    records = normalize_position_page(
        payload, expected_category="linear", instruments={"BTCUSDT": BTC}
    ).positions

    assert len(records) == 1
    assert records[0].leverage is None
    assert records[0].liquidation_price is None
    assert records[0].initial_margin == Decimal("0")


def test_rejects_unknown_symbol_invalid_hedge_side_and_duplicate_leg() -> None:
    with pytest.raises(ValueError, match="absent from catalog"):
        normalize_position_page(
            response(), expected_category="linear", instruments={}
        )

    wrong_side = response([position(side="Sell", index=1)])
    with pytest.raises(ValueError, match="positionIdx 1"):
        normalize_position_page(
            wrong_side, expected_category="linear", instruments={"BTCUSDT": BTC}
        )

    duplicate = response([position(), position()])
    with pytest.raises(ValueError, match="duplicate"):
        normalize_position_page(
            duplicate, expected_category="linear", instruments={"BTCUSDT": BTC}
        )


def test_rejects_api_category_and_numeric_errors() -> None:
    failed = response()
    failed["retCode"] = 10001
    with pytest.raises(ValueError, match="10001"):
        normalize_position_page(
            failed, expected_category="linear", instruments={"BTCUSDT": BTC}
        )

    wrong_category = response()
    wrong_category["result"]["category"] = "inverse"
    with pytest.raises(ValueError, match="category"):
        normalize_position_page(
            wrong_category,
            expected_category="linear",
            instruments={"BTCUSDT": BTC},
        )

    invalid = response()
    invalid["result"]["list"][0]["markPrice"] = "NaN"
    with pytest.raises(ValueError, match="mark_price"):
        normalize_position_page(
            invalid, expected_category="linear", instruments={"BTCUSDT": BTC}
        )
