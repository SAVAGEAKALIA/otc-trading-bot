"""Canonical IQ Option API boundary.

The third-party websocket client remains an implementation detail. Platform
services depend on this narrow protocol and can use a fake in tests.
"""

from __future__ import annotations

from typing import Any, Protocol


class IQOptionAPI(Protocol):
    def connect(self) -> Any: ...
    def check_connect(self) -> bool: ...
    def buy(self, amount: float, asset: str, direction: str, duration: int) -> Any: ...


def build_legacy_api(email: str, password: str, *, ssid: str | None = None) -> Any:
    """Construct the legacy client only at the broker composition boundary."""
    from trading_platform.vendor.iqoptionapi.iqoptionapi.stable_api import IQ_Option

    api = IQ_Option(email, password)
    if ssid:
        api.set_ssid(ssid)
    return api
