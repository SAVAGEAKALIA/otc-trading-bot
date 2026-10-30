"""Portable SQLAlchemy schema with PostgreSQL-compatible types."""

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.types import TypeDecorator


class ExactNumeric(TypeDecorator):
    """Exact Decimal on SQLite tests and NUMERIC(38,18) on PostgreSQL."""

    impl = Numeric(38, 18)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(80))
        return dialect.type_descriptor(Numeric(38, 18))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(value) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        from decimal import Decimal

        return Decimal(str(value))


metadata = MetaData()

orders = Table(
    "orders",
    metadata,
    Column("client_order_id", String(64), primary_key=True),
    Column("environment", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("broker_order_id", String(128), nullable=True),
    Column("intent", JSON, nullable=False),
    Column("version", Integer, nullable=False, default=1),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

order_events = Table(
    "order_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_key", String(160), nullable=False, unique=True),
    Column(
        "client_order_id",
        String(64),
        ForeignKey("orders.client_order_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("status", String(32), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)

executions = Table(
    "executions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("venue_execution_id", String(128), nullable=False),
    Column(
        "client_order_id",
        String(64),
        ForeignKey("orders.client_order_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("quantity", ExactNumeric(), nullable=False),
    Column("price", ExactNumeric(), nullable=False),
    Column("fee", ExactNumeric(), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("client_order_id", "venue_execution_id", name="uq_execution_venue_id"),
)

outbox = Table(
    "outbox",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_key", String(160), nullable=False, unique=True),
    Column("topic", String(100), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("last_error", Text, nullable=True),
)

account_snapshots = Table(
    "account_snapshots",
    metadata,
    Column("snapshot_id", String(128), primary_key=True),
    Column("venue", String(32), nullable=False),
    Column("environment", String(32), nullable=False),
    Column("snapshot", JSON, nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

account_balances = Table(
    "account_balances",
    metadata,
    Column("venue", String(32), primary_key=True),
    Column("environment", String(32), primary_key=True),
    Column("asset", String(32), primary_key=True),
    Column("total", ExactNumeric(), nullable=False),
    Column("available", ExactNumeric(), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
)

positions = Table(
    "positions",
    metadata,
    Column("venue", String(32), primary_key=True),
    Column("environment", String(32), primary_key=True),
    Column("product_type", String(32), primary_key=True),
    Column("symbol", String(64), primary_key=True),
    Column("position_idx", Integer, primary_key=True, default=0),
    Column("settlement_asset", String(32), nullable=False),
    Column("signed_quantity", ExactNumeric(), nullable=False),
    Column("average_entry_price", ExactNumeric(), nullable=False),
    Column("mark_price", ExactNumeric(), nullable=False),
    Column("unrealized_pnl", ExactNumeric(), nullable=False),
    Column("leverage", ExactNumeric(), nullable=False),
    Column("liquidation_price", ExactNumeric(), nullable=True),
    Column("as_of", DateTime(timezone=True), nullable=False),
)

balance_reservations = Table(
    "balance_reservations",
    metadata,
    Column("reservation_id", String(128), primary_key=True),
    Column(
        "client_order_id",
        String(64),
        ForeignKey("orders.client_order_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("venue", String(32), nullable=False),
    Column("environment", String(32), nullable=False),
    Column("asset", String(32), nullable=False),
    Column("amount", ExactNumeric(), nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("released_at", DateTime(timezone=True), nullable=True),
)

signal_decisions = Table(
    "signal_decisions",
    metadata,
    Column("signal_id", String(36), primary_key=True),
    Column("environment", String(32), nullable=False),
    Column("venue", String(32), nullable=False),
    Column("product_type", String(32), nullable=False),
    Column("symbol", String(64), nullable=False),
    Column("proposal", JSON, nullable=False),
    Column("risk_decision", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

binary_settlements = Table(
    "binary_settlements",
    metadata,
    Column("venue_settlement_id", String(128), primary_key=True),
    Column(
        "client_order_id",
        String(64),
        ForeignKey("orders.client_order_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("broker_order_id", String(128), nullable=False),
    Column("outcome", String(16), nullable=False),
    Column("stake", ExactNumeric(), nullable=False),
    Column("gross_return", ExactNumeric(), nullable=False),
    Column("net_pnl", ExactNumeric(), nullable=False),
    Column("settlement_asset", String(32), nullable=False),
    Column("settled_at", DateTime(timezone=True), nullable=False),
    Column("source", String(32), nullable=False),
    Column("evidence", JSON, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
)

calibration_provenance = Table(
    "calibration_provenance",
    metadata,
    Column("calibration_id", String(128), primary_key=True),
    Column("model_version", String(128), nullable=False),
    Column("manifest", JSON, nullable=False),
    Column("registered_at", DateTime(timezone=True), nullable=False),
)
