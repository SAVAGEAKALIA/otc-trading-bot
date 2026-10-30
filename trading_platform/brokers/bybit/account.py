"""Normalize and coordinate capability-limited Bybit private account reads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any, Protocol

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId
from trading_platform.storage.projections import (
    AccountSnapshot,
    BalanceProjection,
    PositionProjection,
)

from .positions import BybitPositionRecord, normalize_position_page


_OPEN_STATUSES = frozenset({"New", "PartiallyFilled", "Untriggered", "Triggered"})


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Bybit {name} must be an object")
    return value


def _decimal(
    value: object,
    name: str,
    *,
    positive: bool = False,
    optional: bool = False,
) -> Decimal | None:
    if optional and value in {None, ""}:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Bybit {name} is not decimal") from exc
    if not result.is_finite():
        raise ValueError(f"Bybit {name} must be finite")
    if result < 0 or (positive and result == 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"Bybit {name} must be {qualifier}")
    return result


def _server_time(payload: Mapping[str, Any]) -> datetime:
    try:
        server_ms = int(payload.get("time", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Bybit response time must be Unix milliseconds") from exc
    if server_ms <= 0:
        raise ValueError("Bybit response time must be positive Unix milliseconds")
    return datetime.fromtimestamp(server_ms / 1000, tz=UTC)


def _successful_result(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        code = int(payload.get("retCode", -1))
    except (TypeError, ValueError) as exc:
        raise ValueError("Bybit retCode must be an integer") from exc
    if code != 0:
        raise ValueError(f"Bybit API error {code}: {payload.get('retMsg', '')}")
    return _mapping(payload.get("result"), "result")


@dataclass(frozen=True, slots=True)
class BybitWalletBalance:
    asset: str
    total: Decimal
    available: Decimal

    def __post_init__(self) -> None:
        asset = self.asset.strip().upper()
        if not asset:
            raise ValueError("Bybit wallet asset must not be empty")
        if not self.total.is_finite() or not self.available.is_finite():
            raise ValueError("Bybit wallet balances must be finite")
        if self.total < 0 or self.available < 0 or self.available > self.total:
            raise ValueError("Bybit wallet available balance must be between zero and total")
        object.__setattr__(self, "asset", asset)

    def to_projection(self) -> BalanceProjection:
        return BalanceProjection(self.asset, self.total, self.available)


@dataclass(frozen=True, slots=True)
class BybitWalletPage:
    account_type: str
    balances: tuple[BybitWalletBalance, ...]
    server_time: datetime


@dataclass(frozen=True, slots=True)
class BybitOpenOrder:
    broker_order_id: str
    client_order_id: str
    symbol: str
    side: str
    order_type: str
    status: str
    quantity: Decimal
    price: Decimal | None
    leaves_quantity: Decimal
    cumulative_executed_quantity: Decimal
    average_price: Decimal | None

    def __post_init__(self) -> None:
        for name in ("broker_order_id", "client_order_id", "symbol"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError("Bybit open-order identity is invalid")
            object.__setattr__(self, name, value.upper() if name == "symbol" else value)
        if self.side not in {"Buy", "Sell"}:
            raise ValueError("Bybit open-order side must be Buy or Sell")
        if self.order_type not in {"Market", "Limit"}:
            raise ValueError("Bybit open-order type must be Market or Limit")
        if self.status not in _OPEN_STATUSES:
            raise ValueError("Bybit open-order status is not open")
        if self.quantity <= 0:
            raise ValueError("Bybit open-order quantity must be positive")
        if self.price is not None and self.price <= 0:
            raise ValueError("Bybit open-order price must be positive when reported")
        if self.leaves_quantity < 0 or self.cumulative_executed_quantity < 0:
            raise ValueError("Bybit open-order quantities must be non-negative")
        if self.leaves_quantity > self.quantity or self.cumulative_executed_quantity > self.quantity:
            raise ValueError("Bybit open-order progress cannot exceed order quantity")
        if self.average_price is not None and self.average_price <= 0:
            raise ValueError("Bybit open-order average price must be positive when reported")


@dataclass(frozen=True, slots=True)
class BybitOpenOrderPage:
    category: str
    orders: tuple[BybitOpenOrder, ...]
    next_cursor: str | None
    server_time: datetime


def normalize_wallet_page(
    payload: Mapping[str, Any], *, expected_account_type: str
) -> BybitWalletPage:
    account_type = expected_account_type.strip().upper()
    if account_type != "UNIFIED":
        raise ValueError("Phase 8 wallet normalization supports only UNIFIED accounts")
    result = _successful_result(payload)
    raw_accounts = result.get("list")
    if not isinstance(raw_accounts, list) or len(raw_accounts) != 1:
        raise ValueError("Bybit wallet result must contain exactly one account")
    account = _mapping(raw_accounts[0], "wallet account")
    actual_type = str(account.get("accountType", "")).strip().upper()
    if actual_type != account_type:
        raise ValueError(
            f"Bybit wallet account type {actual_type!r} does not match {account_type!r}"
        )
    raw_coins = account.get("coin")
    if not isinstance(raw_coins, list):
        raise ValueError("Bybit wallet coin list must be an array")
    balances: list[BybitWalletBalance] = []
    for raw in raw_coins:
        item = _mapping(raw, "wallet coin")
        total = _decimal(item.get("walletBalance"), "wallet balance")
        available_value = item.get("availableToWithdraw", item.get("transferableAmount"))
        available = _decimal(available_value, "available wallet balance")
        assert total is not None and available is not None
        balances.append(
            BybitWalletBalance(
                asset=str(item.get("coin", "")),
                total=total,
                available=available,
            )
        )
    assets = [item.asset for item in balances]
    if len(assets) != len(set(assets)):
        raise ValueError("Bybit wallet page contains a duplicate asset")
    return BybitWalletPage(account_type, tuple(balances), _server_time(payload))


def normalize_open_order_page(
    payload: Mapping[str, Any], *, expected_category: str
) -> BybitOpenOrderPage:
    category = expected_category.strip().lower()
    if category not in {"spot", "linear"}:
        raise ValueError("Bybit open-order category must be spot or linear")
    result = _successful_result(payload)
    actual_category = str(result.get("category", "")).strip().lower()
    if actual_category != category:
        raise ValueError(
            f"Bybit open-order category {actual_category!r} does not match {category!r}"
        )
    raw_orders = result.get("list")
    if not isinstance(raw_orders, list):
        raise ValueError("Bybit open-order list must be an array")
    orders: list[BybitOpenOrder] = []
    for raw in raw_orders:
        item = _mapping(raw, "open order")
        quantity = _decimal(item.get("qty"), "open-order quantity", positive=True)
        leaves = _decimal(item.get("leavesQty"), "open-order leaves quantity")
        executed = _decimal(item.get("cumExecQty"), "open-order executed quantity")
        assert quantity is not None and leaves is not None and executed is not None
        orders.append(
            BybitOpenOrder(
                broker_order_id=str(item.get("orderId", "")),
                client_order_id=str(item.get("orderLinkId", "")),
                symbol=str(item.get("symbol", "")),
                side=str(item.get("side", "")).strip(),
                order_type=str(item.get("orderType", "")).strip(),
                status=str(item.get("orderStatus", "")).strip(),
                quantity=quantity,
                price=_decimal(item.get("price"), "open-order price", positive=True, optional=True),
                leaves_quantity=leaves,
                cumulative_executed_quantity=executed,
                average_price=_decimal(
                    item.get("avgPrice"), "open-order average price", positive=True, optional=True
                ),
            )
        )
    identities = [(item.broker_order_id, item.client_order_id) for item in orders]
    if len(identities) != len(set(identities)):
        raise ValueError("Bybit open-order page contains a duplicate identity")
    cursor = str(result.get("nextPageCursor", "")).strip() or None
    return BybitOpenOrderPage(category, tuple(orders), cursor, _server_time(payload))


class BybitPrivateAccountReader(Protocol):
    async def get_wallet_balance(
        self, *, account_type: str, coins: tuple[str, ...] = ()
    ) -> Mapping[str, Any]: ...

    async def get_open_orders(
        self,
        *,
        category: str,
        symbol: str | None = None,
        cursor: str | None = None,
    ) -> Mapping[str, Any]: ...

    async def get_positions(
        self,
        *,
        category: str,
        symbol: str | None = None,
        settle_coin: str | None = None,
        cursor: str | None = None,
    ) -> Mapping[str, Any]: ...


class BybitPrivateAccountClient:
    """Normalize private reads without adding network or write capabilities."""

    def __init__(self, reader: BybitPrivateAccountReader) -> None:
        self._reader = reader

    async def get_wallet_balances(
        self, *, coins: tuple[str, ...] = ()
    ) -> tuple[BybitWalletBalance, ...]:
        payload = await self._reader.get_wallet_balance(
            account_type="UNIFIED", coins=coins
        )
        return normalize_wallet_page(
            payload, expected_account_type="UNIFIED"
        ).balances

    async def get_account_snapshot(
        self,
        *,
        environment: TradingEnvironment,
        instruments: Mapping[str, InstrumentId],
        symbol: str | None = None,
        settle_coin: str | None = None,
        maximum_pages: int = 20,
    ) -> AccountSnapshot:
        if environment in {TradingEnvironment.RESEARCH, TradingEnvironment.BACKTEST}:
            raise ValueError("Bybit account snapshot environment must be an execution environment")
        if not instruments:
            raise ValueError("Bybit account snapshot requires a verified instrument catalog")
        wallet_page = await self._get_wallet_page()
        position_records, position_as_of = await self._get_position_records(
            instruments=instruments,
            symbol=symbol,
            settle_coin=settle_coin,
            maximum_pages=maximum_pages,
        )
        balances = tuple(item.to_projection() for item in wallet_page.balances)
        positions = tuple(to_projection(item) for item in position_records)
        as_of = max(wallet_page.server_time, position_as_of)
        snapshot_id = _snapshot_id(
            environment=environment,
            as_of=as_of,
            balances=balances,
            positions=positions,
        )
        return AccountSnapshot(
            snapshot_id=snapshot_id,
            venue="BYBIT",
            environment=environment,
            as_of=as_of,
            balances=balances,
            positions=positions,
        )

    async def _get_wallet_page(self) -> BybitWalletPage:
        payload = await self._reader.get_wallet_balance(account_type="UNIFIED", coins=())
        return normalize_wallet_page(payload, expected_account_type="UNIFIED")

    async def _get_position_records(
        self,
        *,
        instruments: Mapping[str, InstrumentId],
        symbol: str | None,
        settle_coin: str | None,
        maximum_pages: int,
    ) -> tuple[tuple[BybitPositionRecord, ...], datetime]:
        if maximum_pages <= 0:
            raise ValueError("maximum_pages must be positive")
        cursor: str | None = None
        seen_cursors: set[str] = set()
        records: list[BybitPositionRecord] = []
        latest_server_time: datetime | None = None
        for _ in range(maximum_pages):
            payload = await self._reader.get_positions(
                category="linear",
                symbol=symbol,
                settle_coin=settle_coin,
                cursor=cursor,
            )
            page = normalize_position_page(
                payload, expected_category="linear", instruments=instruments
            )
            records.extend(page.positions)
            latest_server_time = page.server_time
            identities = [(item.instrument.symbol, item.position_index) for item in records]
            if len(identities) != len(set(identities)):
                raise ValueError("Bybit pagination contains a duplicate position leg")
            if page.next_cursor is None:
                assert latest_server_time is not None
                return tuple(records), latest_server_time
            if page.next_cursor in seen_cursors:
                raise ValueError("Bybit position pagination cursor repeated")
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor
        raise RuntimeError("Bybit position pagination exceeded maximum_pages")

    async def get_open_orders(
        self,
        *,
        category: str,
        symbol: str | None = None,
        maximum_pages: int = 20,
    ) -> tuple[BybitOpenOrder, ...]:
        if maximum_pages <= 0:
            raise ValueError("maximum_pages must be positive")
        normalized_category = category.strip().lower()
        cursor: str | None = None
        seen_cursors: set[str] = set()
        records: list[BybitOpenOrder] = []
        for _ in range(maximum_pages):
            payload = await self._reader.get_open_orders(
                category=normalized_category, symbol=symbol, cursor=cursor
            )
            page = normalize_open_order_page(
                payload, expected_category=normalized_category
            )
            records.extend(page.orders)
            identities = [(item.broker_order_id, item.client_order_id) for item in records]
            if len(identities) != len(set(identities)):
                raise ValueError("Bybit open-order pagination contains a duplicate identity")
            if page.next_cursor is None:
                return tuple(records)
            if page.next_cursor in seen_cursors:
                raise ValueError("Bybit open-order pagination cursor repeated")
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor
        raise RuntimeError("Bybit open-order pagination exceeded maximum_pages")

    async def get_positions(
        self,
        *,
        instruments: Mapping[str, InstrumentId],
        symbol: str | None = None,
        settle_coin: str | None = None,
        maximum_pages: int = 20,
    ) -> tuple[BybitPositionRecord, ...]:
        if maximum_pages <= 0:
            raise ValueError("maximum_pages must be positive")
        cursor: str | None = None
        seen_cursors: set[str] = set()
        records: list[BybitPositionRecord] = []
        for _ in range(maximum_pages):
            payload = await self._reader.get_positions(
                category="linear",
                symbol=symbol,
                settle_coin=settle_coin,
                cursor=cursor,
            )
            page = normalize_position_page(
                payload,
                expected_category="linear",
                instruments=instruments,
            )
            records.extend(page.positions)
            identities = [
                (item.instrument.symbol, item.position_index) for item in records
            ]
            if len(identities) != len(set(identities)):
                raise ValueError("Bybit pagination contains a duplicate position leg")
            if page.next_cursor is None:
                return tuple(records)
            if page.next_cursor in seen_cursors:
                raise ValueError("Bybit position pagination cursor repeated")
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor
        raise RuntimeError("Bybit position pagination exceeded maximum_pages")


def to_projection(record: BybitPositionRecord) -> PositionProjection:
    if record.leverage is None:
        raise ValueError("cannot project a position with unknown leverage")
    return PositionProjection(
        instrument=record.instrument,
        signed_quantity=record.signed_quantity,
        average_entry_price=record.average_entry_price,
        mark_price=record.mark_price,
        unrealized_pnl=record.unrealized_pnl,
        leverage=record.leverage,
        liquidation_price=record.liquidation_price,
        position_idx=record.position_index,
    )


def _snapshot_id(
    *,
    environment: TradingEnvironment,
    as_of: datetime,
    balances: tuple[BalanceProjection, ...],
    positions: tuple[PositionProjection, ...],
) -> str:
    record = {
        "environment": environment.value,
        "as_of": as_of.isoformat(),
        "balances": [
            {"asset": item.asset, "total": str(item.total), "available": str(item.available)}
            for item in sorted(balances, key=lambda item: item.asset)
        ],
        "positions": [
            {
                "symbol": item.instrument.symbol,
                "product_type": item.instrument.product_type.value,
                "position_idx": item.position_idx,
                "signed_quantity": str(item.signed_quantity),
                "average_entry_price": str(item.average_entry_price),
                "mark_price": str(item.mark_price),
                "unrealized_pnl": str(item.unrealized_pnl),
                "leverage": str(item.leverage),
                "liquidation_price": (
                    str(item.liquidation_price) if item.liquidation_price is not None else None
                ),
            }
            for item in sorted(
                positions,
                key=lambda item: (item.instrument.symbol, item.position_idx),
            )
        ],
    }
    digest = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return f"bybit-{environment.value}-{digest}"
