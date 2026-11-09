"""Typed JSON boundaries. Quotes and received price proxies are not accepted trades."""
from dataclasses import asdict, dataclass
from decimal import Context, Decimal, InvalidOperation, localcontext
from typing import Literal


def text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


def integer(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def decimal(value: str, name: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{name} is not decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class Observation:
    event_id: str
    broker: str
    asset: str
    product: str
    source: str
    kind: Literal["quote", "mood", "payout"]
    available_ms: int | None
    event_ms: int
    value: str
    clock_id: str
    quality: Literal["received", "bucket_only"] = "received"

    def __post_init__(self):
        for name in ("event_id", "broker", "asset", "product", "source", "clock_id"):
            text(getattr(self, name), name)
        integer(self.event_ms, "event_ms")
        if self.available_ms is not None:
            integer(self.available_ms, "available_ms")
            if self.available_ms < self.event_ms:
                raise ValueError("Normalized source time cannot follow receipt")
        if self.kind not in {"quote", "mood", "payout"} or self.quality not in {"received", "bucket_only"}:
            raise ValueError("Unknown observation kind or availability quality")
        number = decimal(self.value, "value")
        if self.kind == "quote" and number <= 0:
            raise ValueError("Quote must be positive")
        if self.kind == "mood" and not 0 <= number <= 1:
            raise ValueError("Mood must be a fraction")
        if self.kind == "payout" and not 0 <= number <= 2:
            raise ValueError("Payout must be a net profit ratio in [0, 2]")

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Opportunity:
    opportunity_id: str
    broker: str
    asset: str
    product: str
    clock_id: str
    decision_ms: int
    expiry_ms: int
    latest_entry_ms: int
    expiry_basis: Literal["broker_offer", "hypothetical"]
    direction: Literal["call", "put"] | None
    acceptance_delay_ms: int = 0
    evidence_class: str = "received_price_proxy"

    def __post_init__(self):
        for name in ("opportunity_id", "broker", "asset", "product", "clock_id"):
            text(getattr(self, name), name)
        for name in ("decision_ms", "expiry_ms", "latest_entry_ms", "acceptance_delay_ms"):
            integer(getattr(self, name), name)
        if self.expiry_ms <= self.decision_ms or not self.decision_ms <= self.latest_entry_ms < self.expiry_ms:
            raise ValueError("Entry cutoff must be at/after decision and before absolute expiry")
        if self.expiry_basis not in {"broker_offer", "hypothetical"} or self.direction not in {"call", "put", None}:
            raise ValueError("Invalid expiry basis or direction")
        if self.evidence_class != "received_price_proxy":
            raise ValueError("Opportunity replay cannot assert accepted-contract evidence")

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Settlement:
    """Observed broker cash record; it cannot be constructed from quote predictions."""
    broker_order_id: str
    account_mode: Literal["practice", "live"]
    source: Literal["broker_api"]
    outcome: Literal["win", "loss", "tie", "void"]
    stake: str
    gross_return: str
    separately_charged_fee: str
    currency: str
    settled_ms: int
    evidence_id: str

    def __post_init__(self):
        for name in ("broker_order_id", "currency", "evidence_id"):
            text(getattr(self, name), name)
        integer(self.settled_ms, "settled_ms")
        if self.account_mode not in {"practice", "live"} or self.source != "broker_api":
            raise ValueError("Authoritative cash requires broker source and account mode")
        if self.outcome not in {"win", "loss", "tie", "void"}:
            raise ValueError("Unresolved contracts are not settlements")
        stake, gross, fee = (decimal(getattr(self, n), n) for n in ("stake", "gross_return", "separately_charged_fee"))
        if stake <= 0 or gross < 0 or fee < 0:
            raise ValueError("Invalid cash amounts")
        if self.outcome == "win" and gross <= stake:
            raise ValueError("Winning gross return must exceed stake")
        if self.outcome == "loss" and gross != 0:
            raise ValueError("Full-loss record must return zero")
        # Tie/void cash is preserved as reported, not silently forced to a refund.

    @property
    def net_pnl(self) -> Decimal:
        with localcontext(Context(prec=34)):
            return Decimal(self.gross_return) - Decimal(self.stake) - Decimal(self.separately_charged_fee)

    @property
    def unit_return(self) -> Decimal:
        with localcontext(Context(prec=34)):
            return self.net_pnl / Decimal(self.stake)

    def as_record(self) -> dict:
        return asdict(self)
