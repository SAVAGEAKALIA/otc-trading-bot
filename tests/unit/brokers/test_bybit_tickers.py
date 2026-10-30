from decimal import Decimal

import pytest

from trading_platform.brokers.bybit.tickers import normalize_ticker_page
from trading_platform.domain.instruments import InstrumentId, ProductType


def catalog(category: str) -> dict[str, InstrumentId]:
    product = (
        ProductType.SPOT if category == "spot" else ProductType.LINEAR_PERPETUAL
    )
    return {"BTCUSDT": InstrumentId("BYBIT", product, "BTCUSDT", "USDT")}


def ticker_response(category: str = "linear") -> dict:
    item = {
        "symbol": "BTCUSDT",
        "lastPrice": "60000.50",
        "bid1Price": "60000.40",
        "bid1Size": "1.25",
        "ask1Price": "60000.60",
        "ask1Size": "0.75",
    }
    if category == "linear":
        item.update(
            {
                "indexPrice": "59998.00",
                "markPrice": "60001.00",
                "openInterest": "1234.5",
                "fundingRate": "-0.0001",
                "nextFundingTime": "1800003600000",
            }
        )
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {"category": category, "list": [item]},
        "time": 1_800_000_000_000,
    }


def test_normalizes_linear_ticker_without_float_conversion() -> None:
    page = normalize_ticker_page(
        ticker_response(), expected_category="linear", instruments=catalog("linear")
    )

    ticker = page.tickers[0]
    assert ticker.instrument.product_type is ProductType.LINEAR_PERPETUAL
    assert ticker.bid_price == Decimal("60000.40")
    assert ticker.ask_price == Decimal("60000.60")
    assert ticker.mark_price == Decimal("60001.00")
    assert ticker.index_price == Decimal("59998.00")
    assert ticker.funding_rate == Decimal("-0.0001")
    assert ticker.open_interest == Decimal("1234.5")
    assert ticker.next_funding_at is not None


def test_normalizes_spot_with_derivative_fields_absent() -> None:
    ticker = normalize_ticker_page(
        ticker_response("spot"),
        expected_category="spot",
        instruments=catalog("spot"),
    ).tickers[0]

    assert ticker.instrument.product_type is ProductType.SPOT
    assert ticker.mark_price is None
    assert ticker.index_price is None
    assert ticker.funding_rate is None
    assert ticker.next_funding_at is None


def test_rejects_crossed_or_empty_top_of_book() -> None:
    payload = ticker_response()
    payload["result"]["list"][0]["bid1Price"] = "60001"
    payload["result"]["list"][0]["ask1Price"] = "60000"
    with pytest.raises(ValueError, match="bid_price"):
        normalize_ticker_page(
            payload, expected_category="linear", instruments=catalog("linear")
        )

    payload = ticker_response()
    payload["result"]["list"][0]["bid1Size"] = ""
    with pytest.raises(ValueError, match="bid_size"):
        normalize_ticker_page(
            payload, expected_category="linear", instruments=catalog("linear")
        )


def test_rejects_error_category_mismatch_and_duplicate_symbol() -> None:
    failed = ticker_response()
    failed["retCode"] = 10006
    with pytest.raises(ValueError, match="10006"):
        normalize_ticker_page(
            failed, expected_category="linear", instruments=catalog("linear")
        )

    with pytest.raises(ValueError, match="category"):
        normalize_ticker_page(
            ticker_response("spot"),
            expected_category="linear",
            instruments=catalog("linear"),
        )

    duplicate = ticker_response()
    duplicate["result"]["list"].append(
        dict(duplicate["result"]["list"][0])
    )
    with pytest.raises(ValueError, match="duplicate"):
        normalize_ticker_page(
            duplicate,
            expected_category="linear",
            instruments=catalog("linear"),
        )


def test_rejects_symbol_not_present_in_verified_catalog() -> None:
    with pytest.raises(ValueError, match="absent from catalog"):
        normalize_ticker_page(
            ticker_response(), expected_category="linear", instruments={}
        )
