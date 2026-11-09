"""Typed immutable strategy inputs; no broker operation exists in this contract."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

Asset = Literal['EURUSD-OTC', 'GBPUSD-OTC']
Direction = Literal['call', 'put']
Policy = Literal['leader_burst_flat_target_v1', 'three_step_burst_fade_v1']


@dataclass(frozen=True, slots=True)
class Quote:
    asset: Asset
    received_at_ns: int
    source_at_ms: int
    price: Decimal
    event_id: str
    session_id: str
    clock_offset_ms: int
    clock_ok: bool


@dataclass(frozen=True, slots=True)
class Clock:
    received_at_ns: int
    broker_at_receipt_ms: int
    healthy: bool


@dataclass(frozen=True, slots=True)
class Offer:
    asset: Asset
    received_at_ns: int
    event_id: str
    state: Literal['open', 'closed', 'unknown']
    product: Literal['turbo-option']
    requested_duration_minutes: int
    offered_expiries_ms: tuple[int, ...]
    payout_fraction: Decimal | None


@dataclass(frozen=True, slots=True)
class Pattern:
    policy: Policy
    asset: Asset
    decision_ns: int
    direction: Direction | None
    reason: str
    quote_ids: tuple[str, ...] = ()
    role: Literal['preoffer_mechanism_only'] = 'preoffer_mechanism_only'


@dataclass(frozen=True, slots=True)
class Decision:
    policy: Policy
    asset: Asset
    decision_ns: int
    direction: Direction | None
    reason: str
    expiry_ms: int | None = None
    payout_fraction: Decimal | None = None
    quote_ids: tuple[str, ...] = ()
    offer_id: str | None = None
    role: Literal['practice_strategy_proposal'] = 'practice_strategy_proposal'


@dataclass(frozen=True, slots=True)
class Context:
    asset: Asset
    decision_ns: int
    proposed_expiry_ms: int
    quotes: tuple[Quote, ...]
    offers: tuple[Offer, ...]
    clocks: tuple[Clock, ...]
