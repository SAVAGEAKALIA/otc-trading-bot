"""Transactional order ledger repository."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import json
from typing import Iterable
from uuid import UUID

from sqlalchemy import Engine, delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from trading_platform.domain.calibration import CalibrationProvenance
from trading_platform.domain.orders import (
    OrderIntent,
    OrderStatus,
    OrderType,
    ensure_order_transition,
)
from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.serialization import order_intent_from_record, order_intent_to_record
from trading_platform.domain.settlements import BinarySettlement, BinarySettlementOutcome
from trading_platform.domain.time import require_utc

from .models import (
    account_balances,
    account_snapshots,
    balance_reservations,
    binary_settlements,
    calibration_provenance,
    executions,
    order_events,
    orders,
    outbox,
    positions,
    signal_decisions,
)
from .projections import AccountSnapshot, BalanceProjection, PositionProjection
from trading_platform.domain.risk import RiskDecision
from trading_platform.domain.signals import SignalProposal


@dataclass(frozen=True, slots=True)
class LedgerOrder:
    client_order_id: str
    intent: OrderIntent
    status: OrderStatus
    broker_order_id: str | None
    version: int


@dataclass(frozen=True, slots=True)
class LedgerOrderEvent:
    event_key: str
    client_order_id: str
    status: OrderStatus
    payload: dict


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    event_key: str
    topic: str
    payload: dict
    last_error: str | None


@dataclass(frozen=True, slots=True)
class SignalDecisionRecord:
    signal_id: UUID
    environment: str
    venue: str
    product_type: str
    symbol: str
    strategy_id: str
    source: str | None
    calibration_version: str | None
    legacy_disposition: str | None
    approved: bool
    reasons: tuple[str, ...]
    proposal: dict
    risk_decision: dict
    created_at: datetime


class LedgerRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def record_intent(self, intent: OrderIntent) -> LedgerOrder:
        now = datetime.now(UTC)
        record = order_intent_to_record(intent)
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(orders).values(
                        client_order_id=intent.client_order_id,
                        environment=intent.environment.value,
                        status=OrderStatus.INTENT_RECORDED.value,
                        broker_order_id=None,
                        intent=record,
                        version=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
                self._append_event(
                    connection,
                    intent.client_order_id,
                    OrderStatus.INTENT_RECORDED,
                    1,
                    {},
                    now,
                )
        except IntegrityError:
            existing = self.get_order(intent.client_order_id)
            existing_record = json.loads(
                json.dumps(order_intent_to_record(existing.intent))
            )
            incoming_record = json.loads(json.dumps(record))
            if existing_record != incoming_record:
                raise ValueError("client_order_id already belongs to a different intent")
            return existing
        return self.get_order(intent.client_order_id)

    def claim_submission(self, client_order_id: str) -> bool:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(orders)
                .where(
                    orders.c.client_order_id == client_order_id,
                    orders.c.status == OrderStatus.INTENT_RECORDED.value,
                )
                .values(
                    status=OrderStatus.SUBMISSION_STARTED.value,
                    version=orders.c.version + 1,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                return False
            version = connection.execute(
                select(orders.c.version).where(orders.c.client_order_id == client_order_id)
            ).scalar_one()
            self._append_event(
                connection, client_order_id, OrderStatus.SUBMISSION_STARTED, version, {}, now
            )
            return True

    def transition(
        self,
        client_order_id: str,
        next_status: OrderStatus,
        *,
        broker_order_id: str | None = None,
        payload: dict | None = None,
        executions_to_record: Iterable = (),
    ) -> LedgerOrder:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            row = connection.execute(
                select(orders).where(orders.c.client_order_id == client_order_id)
            ).mappings().one()
            current = OrderStatus(row["status"])
            if current is next_status:
                self._record_executions(connection, client_order_id, executions_to_record, now)
                return self._to_order(row)
            ensure_order_transition(current, next_status)
            version = int(row["version"]) + 1
            effective_broker_id = broker_order_id or row["broker_order_id"]
            result = connection.execute(
                update(orders)
                .where(
                    orders.c.client_order_id == client_order_id,
                    orders.c.version == row["version"],
                )
                .values(
                    status=next_status.value,
                    broker_order_id=effective_broker_id,
                    version=version,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise RuntimeError("concurrent order update detected; reconcile before retry")
            self._append_event(
                connection,
                client_order_id,
                next_status,
                version,
                payload or {},
                now,
            )
            self._record_executions(connection, client_order_id, executions_to_record, now)
        return self.get_order(client_order_id)

    def bind_broker_order_id(
        self,
        client_order_id: str,
        broker_order_id: str,
        *,
        expected_broker_order_id: str | None = None,
    ) -> LedgerOrder:
        """Atomically attach the venue order ID discovered after shadow mirroring.

        Shadow acknowledgement creates a durable counterfactual order before
        the legacy broker call. This compare-and-set update replaces only that
        placeholder once the legacy call is accepted; conflicting identities
        fail closed and never overwrite broker truth.
        """
        client_order_id = client_order_id.strip()
        broker_order_id = broker_order_id.strip()
        if not client_order_id or not broker_order_id:
            raise ValueError("order identities must not be empty")
        with self.engine.begin() as connection:
            row = connection.execute(
                select(orders).where(orders.c.client_order_id == client_order_id)
            ).mappings().one()
            current = row["broker_order_id"]
            if expected_broker_order_id is not None and current != expected_broker_order_id:
                if current == broker_order_id:
                    return self._to_order(row)
                raise ValueError("shadow broker order identity mismatch")
            if current not in {None, expected_broker_order_id, broker_order_id}:
                raise ValueError("broker order identity already bound")
            if current == broker_order_id:
                return self._to_order(row)
            now = datetime.now(UTC)
            result = connection.execute(
                update(orders)
                .where(
                    orders.c.client_order_id == client_order_id,
                    orders.c.version == row["version"],
                )
                .values(
                    broker_order_id=broker_order_id,
                    version=orders.c.version + 1,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise RuntimeError("concurrent broker identity update detected")
            self._append_event(
                connection,
                client_order_id,
                OrderStatus(row["status"]),
                int(row["version"]) + 1,
                {"broker_order_id_bound": broker_order_id},
                now,
            )
        return self.get_order(client_order_id)

    def record_executions(self, client_order_id: str, items: Iterable) -> None:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            self._record_executions(connection, client_order_id, items, now)

    def get_order(self, client_order_id: str) -> LedgerOrder:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(orders).where(orders.c.client_order_id == client_order_id)
            ).mappings().one()
        return self._to_order(row)

    def list_open_orders(self) -> list[LedgerOrder]:
        terminal = {
            OrderStatus.FILLED.value,
            OrderStatus.CANCELED.value,
            OrderStatus.REJECTED.value,
            OrderStatus.EXPIRED.value,
        }
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(orders).where(orders.c.status.not_in(terminal)).order_by(orders.c.created_at)
            ).mappings()
            return [self._to_order(row) for row in rows]

    def list_order_events(self, client_order_id: str) -> list[LedgerOrderEvent]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(order_events)
                .where(order_events.c.client_order_id == client_order_id)
                .order_by(order_events.c.id)
            ).mappings()
            return [
                LedgerOrderEvent(
                    event_key=row["event_key"],
                    client_order_id=row["client_order_id"],
                    status=OrderStatus(row["status"]),
                    payload=dict(row["payload"]),
                )
                for row in rows
            ]

    def order_count(self) -> int:
        return self._count(orders)

    def execution_count(self) -> int:
        return self._count(executions)

    def pending_outbox_count(self) -> int:
        with self.engine.connect() as connection:
            return int(
                connection.execute(
                    select(func.count()).select_from(outbox).where(outbox.c.published_at.is_(None))
                ).scalar_one()
            )

    def list_pending_outbox(self, limit: int = 100) -> list[OutboxMessage]:
        if limit < 1:
            raise ValueError("outbox limit must be positive")
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(outbox)
                .where(outbox.c.published_at.is_(None))
                .order_by(outbox.c.id)
                .limit(limit)
            ).mappings()
            return [
                OutboxMessage(
                    event_key=row["event_key"],
                    topic=row["topic"],
                    payload=dict(row["payload"]),
                    last_error=row["last_error"],
                )
                for row in rows
            ]

    def mark_outbox_published(self, event_key: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(outbox)
                .where(outbox.c.event_key == event_key)
                .values(published_at=datetime.now(UTC), last_error=None)
            )

    def record_outbox_error(self, event_key: str, error: str) -> None:
        message = error.strip()
        if not message:
            raise ValueError("outbox error must not be empty")
        with self.engine.begin() as connection:
            connection.execute(
                update(outbox)
                .where(outbox.c.event_key == event_key)
                .values(last_error=message)
            )

    def replace_account_snapshot(self, snapshot: AccountSnapshot) -> bool:
        """Atomically replace one venue/environment projection; return False for duplicate."""
        now = datetime.now(UTC)
        snapshot_record = {
            "balances": [
                {"asset": item.asset, "total": str(item.total), "available": str(item.available)}
                for item in snapshot.balances
            ],
            "positions": [
                {
                    "venue": item.instrument.venue,
                    "product_type": item.instrument.product_type.value,
                    "symbol": item.instrument.symbol,
                    "position_idx": item.position_idx,
                    "settlement_asset": item.instrument.settlement_asset,
                    "signed_quantity": str(item.signed_quantity),
                    "average_entry_price": str(item.average_entry_price),
                    "mark_price": str(item.mark_price),
                    "unrealized_pnl": str(item.unrealized_pnl),
                    "leverage": str(item.leverage),
                    "liquidation_price": (
                        str(item.liquidation_price) if item.liquidation_price is not None else None
                    ),
                }
                for item in snapshot.positions
            ],
        }
        with self.engine.begin() as connection:
            duplicate = connection.execute(
                select(account_snapshots.c.snapshot_id).where(
                    account_snapshots.c.snapshot_id == snapshot.snapshot_id
                )
            ).first()
            if duplicate is not None:
                return False
            connection.execute(
                insert(account_snapshots).values(
                    snapshot_id=snapshot.snapshot_id,
                    venue=snapshot.venue,
                    environment=snapshot.environment.value,
                    snapshot=snapshot_record,
                    as_of=snapshot.as_of,
                    created_at=now,
                )
            )
            scope = (
                account_balances.c.venue == snapshot.venue,
                account_balances.c.environment == snapshot.environment.value,
            )
            connection.execute(delete(account_balances).where(*scope))
            position_scope = (
                positions.c.venue == snapshot.venue,
                positions.c.environment == snapshot.environment.value,
            )
            connection.execute(delete(positions).where(*position_scope))
            if snapshot.balances:
                connection.execute(
                    insert(account_balances),
                    [
                        {
                            "venue": snapshot.venue,
                            "environment": snapshot.environment.value,
                            "asset": item.asset,
                            "total": item.total,
                            "available": item.available,
                            "as_of": snapshot.as_of,
                        }
                        for item in snapshot.balances
                    ],
                )
            if snapshot.positions:
                connection.execute(
                    insert(positions),
                    [
                        {
                            "venue": item.instrument.venue,
                            "environment": snapshot.environment.value,
                            "product_type": item.instrument.product_type.value,
                            "symbol": item.instrument.symbol,
                            "position_idx": item.position_idx,
                            "settlement_asset": item.instrument.settlement_asset,
                            "signed_quantity": item.signed_quantity,
                            "average_entry_price": item.average_entry_price,
                            "mark_price": item.mark_price,
                            "unrealized_pnl": item.unrealized_pnl,
                            "leverage": item.leverage,
                            "liquidation_price": item.liquidation_price,
                            "as_of": snapshot.as_of,
                        }
                        for item in snapshot.positions
                    ],
                )
            self._append_outbox(
                connection,
                event_key=f"account:{snapshot.venue}:{snapshot.environment.value}:{snapshot.snapshot_id}",
                topic="accounts.reconciled",
                payload={
                    "snapshot_id": snapshot.snapshot_id,
                    "venue": snapshot.venue,
                    "environment": snapshot.environment.value,
                    "as_of": snapshot.as_of.isoformat(),
                },
                now=now,
            )
        return True

    def get_account_projection(
        self, venue: str, environment
    ) -> tuple[list[BalanceProjection], list[PositionProjection]]:
        from trading_platform.domain.instruments import InstrumentId, ProductType

        normalized_venue = venue.strip().upper()
        with self.engine.connect() as connection:
            balance_rows = connection.execute(
                select(account_balances).where(
                    account_balances.c.venue == normalized_venue,
                    account_balances.c.environment == environment.value,
                )
            ).mappings()
            position_rows = connection.execute(
                select(positions).where(
                    positions.c.venue == normalized_venue,
                    positions.c.environment == environment.value,
                )
            ).mappings()
            balances_result = [
                BalanceProjection(row["asset"], Decimal(row["total"]), Decimal(row["available"]))
                for row in balance_rows
            ]
            positions_result = [
                PositionProjection(
                    instrument=InstrumentId(
                        row["venue"],
                        ProductType(row["product_type"]),
                        row["symbol"],
                        row["settlement_asset"],
                    ),
                    signed_quantity=Decimal(row["signed_quantity"]),
                    average_entry_price=Decimal(row["average_entry_price"]),
                    mark_price=Decimal(row["mark_price"]),
                    unrealized_pnl=Decimal(row["unrealized_pnl"]),
                    leverage=Decimal(row["leverage"]),
                    liquidation_price=(
                        Decimal(row["liquidation_price"])
                        if row["liquidation_price"] is not None
                        else None
                    ),
                    position_idx=int(row.get("position_idx", 0)),
                )
                for row in position_rows
            ]
        return balances_result, positions_result

    def reserve_balance(
        self,
        *,
        reservation_id: str,
        client_order_id: str,
        venue: str,
        environment,
        asset: str,
        amount: Decimal,
    ) -> bool:
        """Reserve broker-available balance; return False for an exact duplicate."""
        reservation_id = reservation_id.strip()
        venue = venue.strip().upper()
        asset = asset.strip().upper()
        if not reservation_id or not venue or not asset or amount <= 0:
            raise ValueError("reservation identifiers and positive amount are required")
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(balance_reservations).where(
                    balance_reservations.c.reservation_id == reservation_id
                )
            ).mappings().first()
            expected = (client_order_id, venue, environment.value, asset, amount)
            if existing is not None:
                actual = (
                    existing["client_order_id"],
                    existing["venue"],
                    existing["environment"],
                    existing["asset"],
                    Decimal(existing["amount"]),
                )
                if actual != expected:
                    raise ValueError("reservation_id already belongs to different funds")
                return False
            balance = connection.execute(
                select(account_balances)
                .where(
                    account_balances.c.venue == venue,
                    account_balances.c.environment == environment.value,
                    account_balances.c.asset == asset,
                )
                .with_for_update()
            ).mappings().first()
            if balance is None:
                raise ValueError("broker balance projection is missing")
            reserved = connection.execute(
                select(func.coalesce(func.sum(balance_reservations.c.amount), 0)).where(
                    balance_reservations.c.venue == venue,
                    balance_reservations.c.environment == environment.value,
                    balance_reservations.c.asset == asset,
                    balance_reservations.c.status == "active",
                )
            ).scalar_one()
            if Decimal(balance["available"]) - Decimal(reserved) < amount:
                raise ValueError("insufficient available balance after active reservations")
            connection.execute(
                insert(balance_reservations).values(
                    reservation_id=reservation_id,
                    client_order_id=client_order_id,
                    venue=venue,
                    environment=environment.value,
                    asset=asset,
                    amount=amount,
                    status="active",
                    created_at=now,
                )
            )
            self._append_outbox(
                connection,
                f"reservation:{reservation_id}:active",
                "balances.reserved",
                {
                    "reservation_id": reservation_id,
                    "client_order_id": client_order_id,
                    "venue": venue,
                    "environment": environment.value,
                    "asset": asset,
                    "amount": str(amount),
                },
                now,
            )
        return True

    def release_reservation(self, reservation_id: str) -> bool:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            row = connection.execute(
                select(balance_reservations).where(
                    balance_reservations.c.reservation_id == reservation_id
                )
            ).mappings().one()
            if row["status"] == "released":
                return False
            connection.execute(
                update(balance_reservations)
                .where(balance_reservations.c.reservation_id == reservation_id)
                .values(status="released", released_at=now)
            )
            self._append_outbox(
                connection,
                f"reservation:{reservation_id}:released",
                "balances.released",
                {"reservation_id": reservation_id, "client_order_id": row["client_order_id"]},
                now,
            )
        return True

    def available_after_reservations(self, venue: str, environment, asset: str) -> Decimal:
        venue = venue.strip().upper()
        asset = asset.strip().upper()
        with self.engine.connect() as connection:
            available = connection.execute(
                select(account_balances.c.available).where(
                    account_balances.c.venue == venue,
                    account_balances.c.environment == environment.value,
                    account_balances.c.asset == asset,
                )
            ).scalar_one()
            reserved = connection.execute(
                select(func.coalesce(func.sum(balance_reservations.c.amount), 0)).where(
                    balance_reservations.c.venue == venue,
                    balance_reservations.c.environment == environment.value,
                    balance_reservations.c.asset == asset,
                    balance_reservations.c.status == "active",
                )
            ).scalar_one()
        return Decimal(available) - Decimal(reserved)

    def record_signal_decision(
        self,
        signal: SignalProposal,
        decision: RiskDecision,
        *,
        metadata: dict | None = None,
    ) -> bool:
        if signal.signal_id != decision.signal_id:
            raise ValueError("signal and risk decision IDs differ")
        if signal.environment is not decision.environment:
            raise ValueError("signal and risk decision environments differ")
        now = datetime.now(UTC)
        proposal = {
            "strategy_id": signal.strategy_id,
            "action": signal.action.value,
            "confidence": str(signal.confidence),
            "decision_at": signal.decision_at.isoformat(),
            "expires_at": signal.expires_at.isoformat(),
            "model_version": signal.model_version,
            "config_version": signal.config_version,
            "features": dict(signal.features),
            "metadata": metadata or {},
        }
        risk_record = {
            "decision_id": str(decision.decision_id),
            "is_approved": decision.is_approved,
            "limits_snapshot": dict(decision.limits_snapshot),
            "reasons": list(decision.reasons),
        }
        proposal = json.loads(json.dumps(proposal))
        risk_record = json.loads(json.dumps(risk_record))
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(signal_decisions).values(
                        signal_id=str(signal.signal_id),
                        environment=signal.environment.value,
                        venue=signal.instrument.venue,
                        product_type=signal.instrument.product_type.value,
                        symbol=signal.instrument.symbol,
                        proposal=proposal,
                        risk_decision=risk_record,
                        created_at=now,
                    )
                )
                self._append_outbox(
                    connection,
                    f"signal:{signal.signal_id}:risk",
                    "signals.risk_decided",
                    {
                        "signal_id": str(signal.signal_id),
                        "environment": signal.environment.value,
                        "approved": decision.is_approved,
                        "reasons": list(decision.reasons),
                    },
                    now,
                )
        except IntegrityError:
            with self.engine.connect() as connection:
                existing = connection.execute(
                    select(signal_decisions).where(
                        signal_decisions.c.signal_id == str(signal.signal_id)
                    )
                ).mappings().one()
            if existing["proposal"] != proposal or existing["risk_decision"] != risk_record:
                raise ValueError("signal_id already belongs to a different decision record")
            return False
        return True

    def signal_decision_count(self) -> int:
        return self._count(signal_decisions)

    def register_calibration_provenance(
        self, provenance: CalibrationProvenance
    ) -> bool:
        manifest = json.loads(json.dumps(provenance.to_record()))
        now = datetime.now(UTC)
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(calibration_provenance).values(
                        calibration_id=provenance.calibration_id,
                        model_version=provenance.model_version,
                        manifest=manifest,
                        registered_at=now,
                    )
                )
                self._append_outbox(
                    connection,
                    f"calibration:{provenance.calibration_id}:registered",
                    "models.calibration_registered",
                    {
                        "calibration_id": provenance.calibration_id,
                        "model_version": provenance.model_version,
                        "offline_deployment_approved": (
                            provenance.offline_deployment_approved
                        ),
                    },
                    now,
                )
        except IntegrityError:
            existing = self.get_calibration_provenance(provenance.calibration_id)
            if existing != provenance:
                raise ValueError(
                    "calibration_id already belongs to different provenance"
                )
            return False
        return True

    def find_calibration_provenance(
        self, calibration_id: str
    ) -> CalibrationProvenance | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(calibration_provenance.c.manifest).where(
                    calibration_provenance.c.calibration_id == calibration_id
                )
            ).scalar_one_or_none()
        return CalibrationProvenance.from_record(row) if row is not None else None

    def get_calibration_provenance(
        self, calibration_id: str
    ) -> CalibrationProvenance:
        result = self.find_calibration_provenance(calibration_id)
        if result is None:
            raise KeyError(f"unknown calibration provenance: {calibration_id}")
        return result

    def calibration_provenance_count(self) -> int:
        return self._count(calibration_provenance)

    def record_binary_settlement(self, settlement: BinarySettlement) -> bool:
        now = datetime.now(UTC)
        evidence = json.loads(json.dumps(dict(settlement.evidence)))
        try:
            with self.engine.begin() as connection:
                order_row = connection.execute(
                    select(orders).where(
                        orders.c.client_order_id == settlement.client_order_id
                    )
                ).mappings().one()
                order = self._to_order(order_row)
                if order.intent.order_type is not OrderType.BINARY:
                    raise ValueError("settlement requires a binary order")
                if order.broker_order_id != settlement.broker_order_id:
                    raise ValueError("settlement broker_order_id does not match ledger")
                if order.intent.quantity.value != settlement.stake:
                    raise ValueError("settlement stake does not match order")
                if order.intent.instrument.settlement_asset != settlement.settlement_asset:
                    raise ValueError("settlement asset does not match order")
                if (
                    order.intent.binary_terms is None
                    or settlement.settled_at < order.intent.binary_terms.expires_at
                ):
                    raise ValueError("settlement predates binary expiry")
                connection.execute(
                    insert(binary_settlements).values(
                        venue_settlement_id=settlement.venue_settlement_id,
                        client_order_id=settlement.client_order_id,
                        broker_order_id=settlement.broker_order_id,
                        outcome=settlement.outcome.value,
                        stake=settlement.stake,
                        gross_return=settlement.gross_return,
                        net_pnl=settlement.net_pnl,
                        settlement_asset=settlement.settlement_asset,
                        settled_at=settlement.settled_at,
                        source=settlement.source,
                        evidence=evidence,
                        recorded_at=now,
                    )
                )
                self._append_outbox(
                    connection,
                    f"binary-settlement:{settlement.venue_settlement_id}",
                    "binary.settled",
                    {
                        "venue_settlement_id": settlement.venue_settlement_id,
                        "client_order_id": settlement.client_order_id,
                        "broker_order_id": settlement.broker_order_id,
                        "outcome": settlement.outcome.value,
                        "net_pnl": str(settlement.net_pnl),
                        "settlement_asset": settlement.settlement_asset,
                        "settled_at": settlement.settled_at.isoformat(),
                        "source": settlement.source,
                    },
                    now,
                )
        except IntegrityError:
            with self.engine.connect() as connection:
                row = connection.execute(
                    select(binary_settlements).where(
                        (binary_settlements.c.client_order_id == settlement.client_order_id)
                        | (
                            binary_settlements.c.venue_settlement_id
                            == settlement.venue_settlement_id
                        )
                    )
                ).mappings().one()
            if self._to_binary_settlement(row) != settlement:
                raise ValueError("settlement identity already belongs to different evidence")
            return False
        return True

    def get_binary_settlement(self, client_order_id: str) -> BinarySettlement:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(binary_settlements).where(
                    binary_settlements.c.client_order_id == client_order_id
                )
            ).mappings().one()
        return self._to_binary_settlement(row)

    def list_due_unsettled_binary_orders(
        self, now: datetime, environment: TradingEnvironment
    ) -> list[LedgerOrder]:
        require_utc(now, "now")
        with self.engine.connect() as connection:
            settled_ids = set(
                connection.execute(
                    select(binary_settlements.c.client_order_id)
                ).scalars()
            )
            rows = connection.execute(
                select(orders).order_by(orders.c.client_order_id)
            ).mappings()
            candidates = [self._to_order(row) for row in rows]
        return [
            order
            for order in candidates
            if order.client_order_id not in settled_ids
            and order.intent.environment is environment
            and order.broker_order_id is not None
            and order.status in {OrderStatus.ACKNOWLEDGED, OrderStatus.FILLED}
            and order.intent.order_type is OrderType.BINARY
            and order.intent.binary_terms is not None
            and order.intent.binary_terms.expires_at <= now
        ]

    def binary_settlement_count(self) -> int:
        return self._count(binary_settlements)

    def list_signal_decisions(self) -> list[SignalDecisionRecord]:
        """Return immutable decision evidence in a reproducible order."""
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(signal_decisions).order_by(signal_decisions.c.signal_id)
            ).mappings()
            return [self._to_signal_decision(row) for row in rows]

    def _count(self, table) -> int:
        with self.engine.connect() as connection:
            return int(connection.execute(select(func.count()).select_from(table)).scalar_one())

    @staticmethod
    def _to_order(row) -> LedgerOrder:
        return LedgerOrder(
            client_order_id=row["client_order_id"],
            intent=order_intent_from_record(row["intent"]),
            status=OrderStatus(row["status"]),
            broker_order_id=row["broker_order_id"],
            version=int(row["version"]),
        )

    @staticmethod
    def _to_signal_decision(row) -> SignalDecisionRecord:
        proposal = dict(row["proposal"])
        risk_decision = dict(row["risk_decision"])
        features = proposal.get("features") or {}
        metadata_record = proposal.get("metadata") or {}
        return SignalDecisionRecord(
            signal_id=UUID(row["signal_id"]),
            environment=row["environment"],
            venue=row["venue"],
            product_type=row["product_type"],
            symbol=row["symbol"],
            strategy_id=proposal["strategy_id"],
            source=features.get("source"),
            calibration_version=proposal.get("model_version"),
            legacy_disposition=metadata_record.get("legacy_disposition"),
            approved=bool(risk_decision["is_approved"]),
            reasons=tuple(risk_decision.get("reasons") or ()),
            proposal=proposal,
            risk_decision=risk_decision,
            created_at=row["created_at"],
        )

    @staticmethod
    def _to_binary_settlement(row) -> BinarySettlement:
        settled_at = row["settled_at"]
        if settled_at.tzinfo is None:
            settled_at = settled_at.replace(tzinfo=UTC)
        return BinarySettlement(
            venue_settlement_id=row["venue_settlement_id"],
            client_order_id=row["client_order_id"],
            broker_order_id=row["broker_order_id"],
            outcome=BinarySettlementOutcome(row["outcome"]),
            stake=Decimal(row["stake"]),
            gross_return=Decimal(row["gross_return"]),
            net_pnl=Decimal(row["net_pnl"]),
            settlement_asset=row["settlement_asset"],
            settled_at=settled_at,
            source=row["source"],
            evidence=dict(row["evidence"]),
        )

    @staticmethod
    def _append_event(connection, client_order_id, status, version, payload, now) -> None:
        event_key = f"{client_order_id}:{version}:{status.value}"
        event_payload = {
            "client_order_id": client_order_id,
            "status": status.value,
            **payload,
        }
        connection.execute(
            insert(order_events).values(
                event_key=event_key,
                client_order_id=client_order_id,
                status=status.value,
                payload=event_payload,
                occurred_at=now,
            )
        )
        LedgerRepository._append_outbox(
            connection, event_key, "orders.lifecycle", event_payload, now
        )

    @staticmethod
    def _append_outbox(connection, event_key, topic, payload, now) -> None:
        connection.execute(
            insert(outbox).values(
                event_key=event_key,
                topic=topic,
                payload=payload,
                created_at=now,
            )
        )

    @staticmethod
    def _record_executions(connection, client_order_id, items, now) -> None:
        for item in items:
            exists = connection.execute(
                select(executions.c.id).where(
                    executions.c.client_order_id == client_order_id,
                    executions.c.venue_execution_id == item.execution_id,
                )
            ).first()
            if exists is not None:
                continue
            connection.execute(
                insert(executions).values(
                    venue_execution_id=item.execution_id,
                    client_order_id=client_order_id,
                    quantity=item.quantity,
                    price=item.price,
                    fee=item.fee,
                    occurred_at=now,
                )
            )
