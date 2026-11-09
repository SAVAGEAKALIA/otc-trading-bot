"""Versioned strategy boundary. These values never authorize broker orders."""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

ASSETS = ('EURUSD-OTC', 'GBPUSD-OTC')
POLICIES = ('legacy_mhi3_causal', 'legacy_exhaustion_causal')


class InvalidInput(ValueError):
    pass


def integer(value, name):
    if type(value) is not int or value < 0:
        raise InvalidInput(name + ' must be an exact nonnegative integer')
    return value


def number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise InvalidInput(name + ' must be a finite numeric value excluding bool')
    return value


def receiver_age_ms(decision_ns, received_ns):
    integer(decision_ns, 'decision_ns')
    integer(received_ns, 'received_ns')
    if received_ns > decision_ns:
        raise InvalidInput('future receipt')
    difference = decision_ns - received_ns
    return (difference + 999999) // 1000000


def validate_universe(assets):
    if type(assets) is not tuple or not assets or len(assets) > 256:
        raise InvalidInput('execution universe must be a nonempty frozen tuple of at most256 assets')
    if any(type(asset) is not str or not re.fullmatch(r'[A-Z0-9][A-Z0-9._/-]{0,59}-OTC', asset)
           for asset in assets) or len(set(assets)) != len(assets):
        raise InvalidInput('execution universe needs unique named OTC assets')
    return assets


@dataclass(frozen=True, slots=True)
class Candle:
    asset: str
    start_ms: int
    duration_ms: int
    received_ns: int
    broker_at_receipt_ms: int
    open: float
    high: float
    low: float
    close: float
    finalized: bool
    clock_status: str = 'ok'


@dataclass(frozen=True, slots=True)
class Quote:
    asset: str
    received_ns: int
    broker_at_receipt_ms: int
    price: float
    clock_status: str = 'ok'


@dataclass(frozen=True, slots=True)
class Offer:
    asset: str
    product: str
    received_ns: int
    broker_at_receipt_ms: int
    payout: float
    expiry_ms: int
    purchase_deadline_ms: int
    active: bool
    status: str
    clock_status: str = 'ok'


@dataclass(frozen=True, slots=True)
class Signal:
    schema: str
    policy: str
    asset: str
    decision_ns: int
    direction: str | None
    reason: str
    evidence_sha256: str | None
    requested_expiry_ms: int | None
    score: float | None = None
    capital_permission: bool = False

    @property
    def should_trade(self):
        return self.direction in ('call', 'put')
