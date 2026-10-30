"""Execute capability-limited Bybit private reads with fresh signatures."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
import json
from typing import Any, Protocol

from .http_transport import RawHttpResponse, TRANSIENT_STATUSES
from .private_read import BybitPrivateReadSigner, SignedPrivateReadRequest
from .time_sync import BybitClockSample


class ClockSampleProvider(Protocol):
    async def sample(self) -> BybitClockSample: ...


class PrivateReadBackend(Protocol):
    async def get(
        self,
        url: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
        *,
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> RawHttpResponse: ...


class BybitPrivateReadClient:
    def __init__(
        self,
        signer: BybitPrivateReadSigner,
        clock_samples: ClockSampleProvider,
        backend: PrivateReadBackend,
        *,
        timeout_seconds: float = 10.0,
        maximum_response_bytes: int = 5 * 1024 * 1024,
        maximum_attempts: int = 3,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if timeout_seconds <= 0 or maximum_response_bytes <= 0 or maximum_attempts < 1:
            raise ValueError("private read HTTP limits must be positive")
        self._signer = signer
        self._clock_samples = clock_samples
        self._backend = backend
        self._timeout_seconds = float(timeout_seconds)
        self._maximum_response_bytes = int(maximum_response_bytes)
        self._maximum_attempts = int(maximum_attempts)
        self._sleep = sleep

    async def get_wallet_balance(
        self, *, account_type: str, coins: tuple[str, ...] = ()
    ) -> Mapping[str, Any]:
        normalized_account = account_type.strip().upper()
        if normalized_account != "UNIFIED":
            raise ValueError("Phase 8 wallet reads support only UNIFIED accounts")
        parameters = {"accountType": normalized_account}
        if coins:
            normalized_coins = tuple(coin.strip().upper() for coin in coins)
            if any(not coin for coin in normalized_coins):
                raise ValueError("wallet coin filters cannot be empty")
            if len(normalized_coins) != len(set(normalized_coins)):
                raise ValueError("wallet coin filters cannot contain duplicates")
            parameters["coin"] = ",".join(normalized_coins)
        return await self._request("/v5/account/wallet-balance", parameters)

    async def get_positions(
        self,
        *,
        category: str,
        symbol: str | None = None,
        settle_coin: str | None = None,
        cursor: str | None = None,
    ) -> Mapping[str, Any]:
        normalized_category = category.strip().lower()
        if normalized_category != "linear":
            raise ValueError("Phase 8 position reads support only linear perpetuals")
        parameters = {"category": normalized_category}
        if symbol:
            parameters["symbol"] = symbol.strip().upper()
        if settle_coin:
            parameters["settleCoin"] = settle_coin.strip().upper()
        if cursor:
            parameters["cursor"] = cursor.strip()
        return await self._request("/v5/position/list", parameters)

    async def get_open_orders(
        self,
        *,
        category: str,
        symbol: str | None = None,
        cursor: str | None = None,
    ) -> Mapping[str, Any]:
        normalized_category = category.strip().lower()
        if normalized_category not in {"spot", "linear"}:
            raise ValueError("open-order category must be spot or linear")
        parameters = {"category": normalized_category}
        if symbol:
            parameters["symbol"] = symbol.strip().upper()
        if cursor:
            parameters["cursor"] = cursor.strip()
        return await self._request("/v5/order/realtime", parameters)

    async def _request(
        self, path: str, parameters: Mapping[str, str]
    ) -> Mapping[str, Any]:
        for attempt in range(1, self._maximum_attempts + 1):
            sample = await self._clock_samples.sample()
            request = self._signer.sign_get(
                path, parameters, clock_sample=sample
            )
            try:
                response = await self._execute(request)
            except (ConnectionError, TimeoutError):
                if attempt >= self._maximum_attempts:
                    raise
                await self._sleep(0.25 * (2 ** (attempt - 1)))
                continue
            if len(response.content) > self._maximum_response_bytes:
                raise ValueError("Bybit private response exceeds maximum response bytes")
            if response.status in TRANSIENT_STATUSES:
                if attempt >= self._maximum_attempts:
                    raise RuntimeError(
                        f"Bybit private transient HTTP {response.status} exhausted retries"
                    )
                await self._sleep(0.25 * (2 ** (attempt - 1)))
                continue
            payload = self._decode(response)
            code = int(payload.get("retCode", -1))
            if code == 10006:
                if attempt >= self._maximum_attempts:
                    raise RuntimeError("Bybit private rate limit exhausted retries")
                await self._sleep(0.25 * (2 ** (attempt - 1)))
                continue
            if code != 0:
                raise ValueError(f"Bybit API error {code}: {payload.get('retMsg', '')}")
            return payload
        raise RuntimeError("Bybit private read retry loop terminated unexpectedly")

    async def _execute(self, request: SignedPrivateReadRequest) -> RawHttpResponse:
        return await self._backend.get(
            request.url,
            dict(request.parameters),
            request.headers,
            timeout_seconds=self._timeout_seconds,
            maximum_bytes=self._maximum_response_bytes,
        )

    def _decode(self, response: RawHttpResponse) -> Mapping[str, Any]:
        if len(response.content) > self._maximum_response_bytes:
            raise ValueError("Bybit private response exceeds maximum response bytes")
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Bybit private HTTP {response.status}")
        headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
        if "application/json" not in headers.get("content-type", "").lower():
            raise ValueError("Bybit private response must use a JSON content type")
        try:
            payload = json.loads(response.content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Bybit private response contains invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("Bybit private JSON root must be an object")
        return payload
