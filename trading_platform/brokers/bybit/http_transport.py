"""Bounded unsigned HTTP transport for allowlisted Bybit public endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import json
from typing import Any, Protocol


PUBLIC_BASE_URLS = {
    "mainnet": "https://api.bybit.com",
    "testnet": "https://api-testnet.bybit.com",
}
ALLOWED_PARAMETERS = {
    "/v5/market/time": set(),
    "/v5/market/instruments-info": {"category", "limit", "cursor"},
    "/v5/market/tickers": {"category"},
}
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


@dataclass(frozen=True, slots=True)
class RawHttpResponse:
    status: int
    headers: Mapping[str, str]
    content: bytes


class AsyncHttpBackend(Protocol):
    async def get(
        self,
        url: str,
        params: Mapping[str, str],
        *,
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> RawHttpResponse: ...


class RequestsHttpBackend:
    """Run the existing requests dependency off-loop with streaming size bounds."""

    def __init__(self) -> None:
        import requests

        self._requests = requests

    async def get(
        self,
        url: str,
        params: Mapping[str, str],
        *,
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> RawHttpResponse:
        try:
            return await asyncio.to_thread(
                self._get_sync, url, params, timeout_seconds, maximum_bytes
            )
        except self._requests.exceptions.Timeout as exc:
            raise TimeoutError("Bybit public request timed out") from exc
        except self._requests.exceptions.ConnectionError as exc:
            raise ConnectionError("Bybit public request failed to connect") from exc

    def _get_sync(
        self,
        url: str,
        params: Mapping[str, str],
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> RawHttpResponse:
        response = self._requests.get(
            url,
            params=dict(params),
            headers={
                "Accept": "application/json",
                "User-Agent": "trading-platform/phase8",
            },
            timeout=timeout_seconds,
            allow_redirects=False,
            stream=True,
        )
        declared = response.headers.get("content-length")
        if declared is not None and int(declared) > maximum_bytes:
            response.close()
            raise ValueError("Bybit response exceeds maximum response bytes")
        chunks = []
        size = 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                size += len(chunk)
                if size > maximum_bytes:
                    raise ValueError("Bybit response exceeds maximum response bytes")
                chunks.append(chunk)
            return RawHttpResponse(
                status=int(response.status_code),
                headers={str(k).lower(): str(v) for k, v in response.headers.items()},
                content=b"".join(chunks),
            )
        finally:
            response.close()


class BybitPublicHttpTransport:
    def __init__(
        self,
        backend: AsyncHttpBackend,
        *,
        environment: str,
        timeout_seconds: float = 10.0,
        maximum_response_bytes: int = 5 * 1024 * 1024,
        maximum_attempts: int = 3,
        maximum_retry_delay: float = 5.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        normalized = environment.strip().lower()
        if normalized not in PUBLIC_BASE_URLS:
            raise ValueError("Bybit public environment must be mainnet or testnet")
        if timeout_seconds <= 0 or maximum_response_bytes <= 0:
            raise ValueError("timeout and maximum response bytes must be positive")
        if maximum_attempts < 1 or maximum_retry_delay < 0:
            raise ValueError("retry configuration is invalid")
        self._backend = backend
        self._base_url = PUBLIC_BASE_URLS[normalized]
        self._timeout_seconds = float(timeout_seconds)
        self._maximum_response_bytes = int(maximum_response_bytes)
        self._maximum_attempts = int(maximum_attempts)
        self._maximum_retry_delay = float(maximum_retry_delay)
        self._sleep = sleep

    async def get_json(
        self, path: str, params: Mapping[str, str]
    ) -> Mapping[str, Any]:
        allowed = ALLOWED_PARAMETERS.get(path)
        if allowed is None:
            raise ValueError("Bybit public path is not allowlisted")
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            raise ValueError("Bybit public parameters are not allowlisted: " + ", ".join(unexpected))
        normalized_params = {str(key): str(value) for key, value in params.items()}
        url = self._base_url + path
        for attempt in range(1, self._maximum_attempts + 1):
            try:
                response = await self._backend.get(
                    url,
                    normalized_params,
                    timeout_seconds=self._timeout_seconds,
                    maximum_bytes=self._maximum_response_bytes,
                )
            except (ConnectionError, TimeoutError):
                if attempt >= self._maximum_attempts:
                    raise
                await self._sleep(self._retry_delay(attempt, None))
                continue
            headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
            if len(response.content) > self._maximum_response_bytes:
                raise ValueError("Bybit response exceeds maximum response bytes")
            if response.status in TRANSIENT_STATUSES:
                if attempt >= self._maximum_attempts:
                    raise RuntimeError(
                        f"Bybit transient HTTP {response.status} exhausted retries"
                    )
                await self._sleep(
                    self._retry_delay(attempt, headers.get("retry-after"))
                )
                continue
            if not 200 <= response.status < 300:
                raise RuntimeError(f"Bybit HTTP {response.status}")
            if "application/json" not in headers.get("content-type", "").lower():
                raise ValueError("Bybit response must use a JSON content type")
            try:
                payload = json.loads(response.content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Bybit response contains invalid JSON") from exc
            if not isinstance(payload, Mapping):
                raise ValueError("Bybit JSON root must be an object")
            if int(payload.get("retCode", 0)) == 10006:
                if attempt >= self._maximum_attempts:
                    raise RuntimeError("Bybit API rate limit exhausted retries")
                await self._sleep(
                    self._retry_delay(attempt, headers.get("retry-after"))
                )
                continue
            return payload
        raise RuntimeError("Bybit public HTTP retry loop terminated unexpectedly")

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None:
            try:
                requested = max(0.0, float(retry_after))
            except ValueError:
                requested = 0.25 * (2 ** (attempt - 1))
        else:
            requested = 0.25 * (2 ** (attempt - 1))
        return min(requested, self._maximum_retry_delay)
