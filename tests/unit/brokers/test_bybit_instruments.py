from decimal import Decimal

import pytest

from trading_platform.brokers.bybit.instruments import normalize_instrument_page
from trading_platform.domain.instruments import ProductType


def response(category: str = "linear") -> dict:
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "category": category,
            "nextPageCursor": "next-page",
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "status": "Trading",
                    "baseCoin": "BTC",
                    "quoteCoin": "USDT",
                    "settleCoin": "USDT",
                    "priceFilter": {
                        "minPrice": "0.10",
                        "maxPrice": "1999999.80",
                        "tickSize": "0.10",
                    },
                    "lotSizeFilter": {
                        "minOrderQty": "0.001",
                        "maxOrderQty": "100.000",
                        "qtyStep": "0.001",
                        "minNotionalValue": "5",
                    },
                    "leverageFilter": {"maxLeverage": "100"},
                }
            ],
        },
        "time": 1_800_000_000_000,
    }


def test_normalizes_linear_instrument_constraints() -> None:
    page = normalize_instrument_page(response(), expected_category="linear")

    spec = page.instruments[0]
    assert page.next_cursor == "next-page"
    assert spec.instrument.venue == "BYBIT"
    assert spec.instrument.product_type is ProductType.LINEAR_PERPETUAL
    assert spec.instrument.symbol == "BTCUSDT"
    assert spec.price_tick == Decimal("0.10")
    assert spec.quantity_step == Decimal("0.001")
    assert spec.minimum_notional == Decimal("5")
    assert spec.maximum_leverage == Decimal("100")
    assert spec.is_trading is True


def test_normalizes_spot_without_derivatives_leverage() -> None:
    payload = response("spot")
    item = payload["result"]["list"][0]
    item["settleCoin"] = ""
    item["lotSizeFilter"]["minOrderAmt"] = "10"
    item["lotSizeFilter"].pop("minNotionalValue")
    item.pop("leverageFilter")

    spec = normalize_instrument_page(payload, expected_category="spot").instruments[0]

    assert spec.instrument.product_type is ProductType.SPOT
    assert spec.instrument.settlement_asset == "USDT"
    assert spec.minimum_notional == Decimal("10")
    assert spec.maximum_leverage is None


def test_rejects_bybit_error_and_category_mismatch() -> None:
    failed = response()
    failed["retCode"] = 10001
    failed["retMsg"] = "parameter error"
    with pytest.raises(ValueError, match="10001"):
        normalize_instrument_page(failed, expected_category="linear")

    with pytest.raises(ValueError, match="category"):
        normalize_instrument_page(response("spot"), expected_category="linear")


def test_rejects_invalid_or_incomplete_trading_constraints() -> None:
    payload = response()
    payload["result"]["list"][0]["lotSizeFilter"]["qtyStep"] = "0"

    with pytest.raises(ValueError, match="quantity_step"):
        normalize_instrument_page(payload, expected_category="linear")


def test_rejects_duplicate_symbols_within_page() -> None:
    payload = response()
    payload["result"]["list"].append(dict(payload["result"]["list"][0]))

    with pytest.raises(ValueError, match="duplicate"):
        normalize_instrument_page(payload, expected_category="linear")
