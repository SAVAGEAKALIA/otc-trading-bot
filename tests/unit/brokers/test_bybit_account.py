from datetime import UTC
from decimal import Decimal

import pytest

from trading_platform.brokers.bybit.account import (
    BybitPrivateAccountClient,
    normalize_open_order_page,
    normalize_wallet_page,
)
from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId, ProductType


BTC = InstrumentId("BYBIT", ProductType.LINEAR_PERPETUAL, "BTCUSDT", "USDT")


def wallet_response(items=None, *, cursor="next", category="UNIFIED"):
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "list": [
                {
                    "accountType": category,
                    "coin": items if items is not None else [
                        {"coin": "USDT", "walletBalance": "100.25", "availableToWithdraw": "90.10"}
                    ],
                }
            ],
        },
        "time": 1_800_000_000_000,
    }


def order(order_id="oid-1", link_id="client-1", symbol="BTCUSDT"):
    return {
        "orderId": order_id,
        "orderLinkId": link_id,
        "symbol": symbol,
        "side": "Buy",
        "orderType": "Limit",
        "orderStatus": "New",
        "qty": "0.01",
        "price": "60000",
        "leavesQty": "0.01",
        "cumExecQty": "0",
        "avgPrice": "",
    }


def orders_response(items=None, *, cursor="next", category="linear"):
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "category": category,
            "nextPageCursor": cursor,
            "list": items if items is not None else [order()],
        },
        "time": 1_800_000_000_000,
    }


def position(index=1, side="Buy", size="0.1"):
    return {
        "symbol": "BTCUSDT",
        "side": side,
        "size": size,
        "positionIdx": index,
        "avgPrice": "60000",
        "markPrice": "61000",
        "positionValue": "6100",
        "unrealisedPnl": "100",
        "leverage": "3",
        "liqPrice": "45000",
        "positionIM": "2000",
        "positionMM": "30",
    }


def positions_response(items=None, *, cursor="next"):
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "category": "linear",
            "nextPageCursor": cursor,
            "list": items if items is not None else [position()],
        },
        "time": 1_800_000_000_000,
    }


def test_normalizes_unified_wallet_page_without_float_conversion() -> None:
    page = normalize_wallet_page(wallet_response(), expected_account_type="UNIFIED")
    assert page.account_type == "UNIFIED"
    assert page.balances[0].asset == "USDT"
    assert page.balances[0].total == Decimal("100.25")
    assert page.balances[0].available == Decimal("90.10")
    assert page.server_time.tzinfo is UTC


def test_normalizes_open_orders_and_preserves_decimal_fields() -> None:
    page = normalize_open_order_page(orders_response(), expected_category="linear")
    item = page.orders[0]
    assert item.client_order_id == "client-1"
    assert item.broker_order_id == "oid-1"
    assert item.quantity == Decimal("0.01")
    assert item.price == Decimal("60000")
    assert item.average_price is None


@pytest.mark.asyncio
async def test_builds_deterministic_broker_account_snapshot() -> None:
    reader = Reader(
        wallets=[wallet_response(items=[
            {"coin": "USDT", "walletBalance": "100.25", "availableToWithdraw": "90.10"},
        ], cursor="")],
        positions=[positions_response(items=[position()], cursor="")],
    )
    client = BybitPrivateAccountClient(reader)
    first = await client.get_account_snapshot(
        environment=TradingEnvironment.TESTNET,
        instruments={"BTCUSDT": BTC},
    )
    reader = Reader(
        wallets=[wallet_response(items=[
            {"coin": "USDT", "walletBalance": "100.25", "availableToWithdraw": "90.10"},
        ], cursor="")],
        positions=[positions_response(items=[position()], cursor="")],
    )
    second = await BybitPrivateAccountClient(reader).get_account_snapshot(
        environment=TradingEnvironment.TESTNET,
        instruments={"BTCUSDT": BTC},
    )

    assert first == second
    assert first.snapshot_id.startswith("bybit-testnet-")
    assert first.as_of.isoformat() == "2027-01-15T08:00:00+00:00"
    assert first.balances[0].available == Decimal("90.10")
    assert first.positions[0].position_idx == 1
    assert first.positions[0].signed_quantity == Decimal("0.1")


@pytest.mark.asyncio
async def test_account_snapshot_rejects_unknown_leverage_and_invalid_environment() -> None:
    unknown = position()
    unknown["leverage"] = ""
    reader = Reader(
        wallets=[wallet_response(cursor="")],
        positions=[positions_response(items=[unknown], cursor="")],
    )
    client = BybitPrivateAccountClient(reader)
    with pytest.raises(ValueError, match="unknown leverage"):
        await client.get_account_snapshot(
            environment=TradingEnvironment.TESTNET,
            instruments={"BTCUSDT": BTC},
        )

    with pytest.raises(ValueError, match="environment"):
        await client.get_account_snapshot(
            environment=TradingEnvironment.RESEARCH,
            instruments={"BTCUSDT": BTC},
        )


@pytest.mark.parametrize(
    ("payload_factory", "expected"),
    [
        (lambda: wallet_response(category="CONTRACT"), "account type"),
        (lambda: wallet_response(items=[{"coin": "USDT", "walletBalance": "NaN", "availableToWithdraw": "1"}]), "wallet balance"),
        (lambda: wallet_response(items=[{"coin": "USDT", "walletBalance": "1", "availableToWithdraw": "2"}]), "available"),
        (lambda: orders_response(category="spot"), "category"),
        (lambda: orders_response(items=[order(order_id="", link_id="client-1")]), "identity"),
        (lambda: orders_response(items=[order(), order()]), "duplicate"),
    ],
)
def test_normalizers_fail_closed(payload_factory, expected) -> None:
    with pytest.raises(ValueError, match=expected):
        if "category" in expected or expected == "account type":
            payload = payload_factory()
            if expected == "account type":
                normalize_wallet_page(payload, expected_account_type="UNIFIED")
            else:
                normalize_open_order_page(payload, expected_category="linear")
        else:
            payload = payload_factory()
            if "wallet" in expected or "available" in expected:
                normalize_wallet_page(payload, expected_account_type="UNIFIED")
            else:
                normalize_open_order_page(payload, expected_category="linear")


class Reader:
    def __init__(self, wallets=(), orders=(), positions=()):
        self.wallets = list(wallets)
        self.orders = list(orders)
        self.positions = list(positions)
        self.wallet_calls = []
        self.order_calls = []
        self.position_calls = []

    async def get_wallet_balance(self, **kwargs):
        self.wallet_calls.append(kwargs)
        return self.wallets.pop(0)

    async def get_open_orders(self, **kwargs):
        self.order_calls.append(kwargs)
        return self.orders.pop(0)

    async def get_positions(self, **kwargs):
        self.position_calls.append(kwargs)
        return self.positions.pop(0)


@pytest.mark.asyncio
async def test_private_account_client_paginates_and_rejects_cursor_replay() -> None:
    reader = Reader(
        wallets=[wallet_response(items=[
            {"coin": "USDT", "walletBalance": "100.25", "availableToWithdraw": "90.10"},
            {"coin": "BTC", "walletBalance": "1", "availableToWithdraw": "1"},
        ])],
        orders=[orders_response(cursor="o2"), orders_response(items=[order(order_id="oid-2", link_id="client-2")], cursor="")],
    )
    client = BybitPrivateAccountClient(reader)
    balances = await client.get_wallet_balances()
    open_orders = await client.get_open_orders(category="linear")
    assert [item.asset for item in balances] == ["USDT", "BTC"]
    assert [item.client_order_id for item in open_orders] == ["client-1", "client-2"]
    assert reader.order_calls[1]["cursor"] == "o2"

    repeating = BybitPrivateAccountClient(
        Reader(orders=[
            orders_response(cursor="same"),
            orders_response(
                items=[order(order_id="oid-2", link_id="client-2")],
                cursor="same",
            ),
        ])
    )
    with pytest.raises(ValueError, match="cursor repeated"):
        await repeating.get_open_orders(category="linear")

    limited = BybitPrivateAccountClient(
        Reader(orders=[orders_response(cursor="next")])
    )
    with pytest.raises(RuntimeError, match="maximum_pages"):
        await limited.get_open_orders(category="linear", maximum_pages=1)


@pytest.mark.asyncio
async def test_private_account_client_paginates_distinct_position_legs() -> None:
    reader = Reader(
        positions=[
            positions_response(cursor="p2"),
            positions_response(
                items=[position(index=2, side="Sell", size="0.05")], cursor=""
            ),
        ]
    )
    client = BybitPrivateAccountClient(reader)

    records = await client.get_positions(instruments={"BTCUSDT": BTC})

    assert [(item.position_index, item.signed_quantity) for item in records] == [
        (1, Decimal("0.1")),
        (2, Decimal("-0.05")),
    ]
    assert reader.position_calls[1]["cursor"] == "p2"


@pytest.mark.asyncio
async def test_position_pagination_fails_on_duplicate_leg_cursor_replay_and_limit() -> None:
    duplicate = BybitPrivateAccountClient(
        Reader(
            positions=[
                positions_response(cursor="p2"),
                positions_response(cursor=""),
            ]
        )
    )
    with pytest.raises(ValueError, match="duplicate position leg"):
        await duplicate.get_positions(instruments={"BTCUSDT": BTC})

    replay = BybitPrivateAccountClient(
        Reader(
            positions=[
                positions_response(cursor="same"),
                positions_response(
                    items=[position(index=2, side="Sell")], cursor="same"
                ),
            ]
        )
    )
    with pytest.raises(ValueError, match="cursor repeated"):
        await replay.get_positions(instruments={"BTCUSDT": BTC})

    limited = BybitPrivateAccountClient(
        Reader(positions=[positions_response(cursor="next")])
    )
    with pytest.raises(RuntimeError, match="maximum_pages"):
        await limited.get_positions(
            instruments={"BTCUSDT": BTC}, maximum_pages=1
        )
