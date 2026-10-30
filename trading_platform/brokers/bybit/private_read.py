"""Construct signed Bybit V5 GET requests for private read capabilities only."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import hmac
from types import MappingProxyType
from urllib.parse import urlencode

from trading_platform.execution.clock import Clock

from .http_transport import PUBLIC_BASE_URLS
from .time_sync import BybitClockSample


PRIVATE_READ_PARAMETERS = {
    "/v5/account/wallet-balance": {"accountType", "coin"},
    "/v5/position/list": {
        "category",
        "symbol",
        "baseCoin",
        "settleCoin",
        "limit",
        "cursor",
    },
    "/v5/order/realtime": {
        "category",
        "symbol",
        "baseCoin",
        "settleCoin",
        "orderId",
        "orderLinkId",
        "openOnly",
        "limit",
        "cursor",
    },
}
REQUIRED_PARAMETERS = {
    "/v5/account/wallet-balance": {"accountType"},
    "/v5/position/list": {"category"},
    "/v5/order/realtime": {"category"},
}
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class SignedPrivateReadRequest:
    url: str
    path: str
    query_string: str
    parameters: tuple[tuple[str, str], ...]
    headers: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


class BybitPrivateReadSigner:
    """Sign only allowlisted GET reads; this class cannot submit orders."""

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        environment: str,
        clock: Clock,
        receive_window_ms: int = 5000,
        maximum_clock_sample_age: timedelta = timedelta(seconds=30),
    ) -> None:
        normalized_environment = environment.strip().lower()
        if normalized_environment not in PUBLIC_BASE_URLS:
            raise ValueError("Bybit private environment must be mainnet or testnet")
        normalized_key = api_key.strip()
        if not normalized_key or not api_secret:
            raise ValueError("Bybit API key and secret must not be empty")
        if not 1 <= receive_window_ms <= 10_000:
            raise ValueError("receive_window_ms must be between 1 and 10000")
        if maximum_clock_sample_age <= timedelta(0):
            raise ValueError("maximum clock sample age must be positive")
        self._api_key = normalized_key
        self._api_secret = api_secret.encode("utf-8")
        self._base_url = PUBLIC_BASE_URLS[normalized_environment]
        self._clock = clock
        self._receive_window_ms = int(receive_window_ms)
        self._maximum_clock_sample_age = maximum_clock_sample_age

    def sign_get(
        self,
        path: str,
        parameters: Mapping[str, str],
        *,
        clock_sample: BybitClockSample,
    ) -> SignedPrivateReadRequest:
        allowed = PRIVATE_READ_PARAMETERS.get(path)
        if allowed is None:
            raise ValueError("Bybit private read path is not allowlisted")
        unexpected = sorted(set(parameters) - allowed)
        if unexpected:
            raise ValueError(
                "Bybit private read parameters are not allowlisted: "
                + ", ".join(unexpected)
            )
        missing = sorted(REQUIRED_PARAMETERS[path] - set(parameters))
        if missing:
            raise ValueError(
                "Bybit private read parameters are missing: " + ", ".join(missing)
            )
        normalized = tuple(
            sorted((str(key), str(value)) for key, value in parameters.items())
        )
        if any(not key or not value for key, value in normalized):
            raise ValueError("Bybit private read parameters cannot be empty")
        now = self._clock.now()
        if not clock_sample.healthy:
            raise RuntimeError("Bybit clock sample is unhealthy")
        age = now - clock_sample.response_received_at
        if age < timedelta(0):
            raise RuntimeError("Bybit clock sample is from the future")
        if age > self._maximum_clock_sample_age:
            raise RuntimeError("Bybit clock sample is stale")
        local_microseconds = (
            (now - EPOCH).days * 86_400_000_000
            + (now - EPOCH).seconds * 1_000_000
            + (now - EPOCH).microseconds
        )
        adjusted_ms = int(
            Decimal(local_microseconds) / Decimal("1000") + clock_sample.offset_ms
        )
        query_string = urlencode(normalized)
        receive_window = str(self._receive_window_ms)
        signature_payload = (
            f"{adjusted_ms}{self._api_key}{receive_window}{query_string}"
        )
        signature = hmac.new(
            self._api_secret,
            signature_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return SignedPrivateReadRequest(
            url=self._base_url + path,
            path=path,
            query_string=query_string,
            parameters=normalized,
            headers={
                "X-BAPI-API-KEY": self._api_key,
                "X-BAPI-TIMESTAMP": str(adjusted_ms),
                "X-BAPI-SIGN": signature,
                "X-BAPI-RECV-WINDOW": receive_window,
                "X-BAPI-SIGN-TYPE": "2",
                "Accept": "application/json",
            },
        )
