import pytest

from trading_platform.brokers.bybit.public_client import BybitPublicDataClient

from tests.unit.brokers.test_bybit_instruments import response as instrument_response
from tests.unit.brokers.test_bybit_tickers import ticker_response


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def get_json(self, path, params):
        self.calls.append((path, dict(params)))
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_paginates_instruments_and_fetches_catalog_bound_tickers() -> None:
    first = instrument_response()
    second = instrument_response()
    second["result"]["nextPageCursor"] = ""
    second["result"]["list"][0]["symbol"] = "ETHUSDT"
    second["result"]["list"][0]["baseCoin"] = "ETH"
    ticker = ticker_response()
    transport = FakeTransport([first, second, ticker])
    client = BybitPublicDataClient(transport)

    catalog = await client.get_instruments("linear")
    tickers = await client.get_tickers("linear", catalog=catalog)

    assert [item.instrument.symbol for item in catalog.instruments] == [
        "BTCUSDT",
        "ETHUSDT",
    ]
    assert tickers.tickers[0].instrument is catalog.by_symbol["BTCUSDT"].instrument
    assert transport.calls == [
        ("/v5/market/instruments-info", {"category": "linear", "limit": "1000"}),
        (
            "/v5/market/instruments-info",
            {"category": "linear", "limit": "1000", "cursor": "next-page"},
        ),
        ("/v5/market/tickers", {"category": "linear"}),
    ]


@pytest.mark.asyncio
async def test_repeated_cursor_fails_instead_of_looping_forever() -> None:
    transport = FakeTransport([instrument_response(), instrument_response()])

    with pytest.raises(RuntimeError, match="repeated cursor"):
        await BybitPublicDataClient(transport).get_instruments("linear")


@pytest.mark.asyncio
async def test_cross_page_duplicate_symbol_is_rejected() -> None:
    first = instrument_response()
    second = instrument_response()
    second["result"]["nextPageCursor"] = ""
    transport = FakeTransport([first, second])

    with pytest.raises(ValueError, match="duplicate symbol"):
        await BybitPublicDataClient(transport).get_instruments("linear")


def test_client_exposes_no_order_or_private_account_methods() -> None:
    public_methods = set(dir(BybitPublicDataClient))
    assert "submit_order" not in public_methods
    assert "get_balances" not in public_methods
    assert "get_positions" not in public_methods
