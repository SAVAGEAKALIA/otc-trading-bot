"""Exact monetary and quantity value objects."""

from dataclasses import dataclass
from decimal import Decimal


def _require_finite(value: Decimal, field_name: str) -> None:
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        _require_finite(self.amount, "amount")
        if self.amount < 0:
            raise ValueError("money amount cannot be negative")
        currency = self.currency.strip().upper()
        if not currency or not currency.replace("_", "").isalnum():
            raise ValueError("currency must be a non-empty asset code")
        object.__setattr__(self, "currency", currency)


@dataclass(frozen=True, slots=True)
class Quantity:
    value: Decimal

    def __post_init__(self) -> None:
        _require_finite(self.value, "quantity")
        if self.value <= 0:
            raise ValueError("quantity must be strictly positive")

