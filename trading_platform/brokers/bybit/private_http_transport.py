"""Allowlisted bounded HTTP executor for signed Bybit private reads."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
import json
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlsplit

from .http_transport import PUBLIC_BASE_URLS, RawHttpResponse, TRANSIENT_STATUSES
from .private_read import PRIVATE_READ_PARAMETERS, REQUIRED_PARAMETERS


class PrivateHttpBackend(Protocol):
    async def get(
        self,
        url: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
        *,
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> RawHttpResponse: ...


class RequestsPrivateHttpBackend:
    """Run requests off-loop with redirect denial and streaming bounds."""

    def __init__(self) -> None:
        import requests

        self._requests = requests

    async def get(
        self,
        url: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
        *,
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> RawHttpResponse:
        try:
            return await asyncio.to_thread(
                self._get_sync,
                url,
                params,
                headers,
                timeout_seconds,
                maximum_bytes,
            )
        except self._requests.exceptions.Timeout as exc:
            raise TimeoutError("Bybit private request timed out") from exc
        except self._requests.exceptions.ConnectionError as exc:
            raise ConnectionError("Bybit private request failed to connect") from exc

    def _get_sync(
        self,
        url: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> RawHttpResponse:
        response = self._requests.get(
            url,
            params=dict(params),
            headers=dict(headers),
            timeout=timeout_seconds,
            allow_redirects=False,
            stream=True,
        )
        declared = response.headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > maximum_bytes:
                    response.close()
                    raise ValueError("Bybit private response exceeds maximum response bytes")
            except ValueError:
                response.close()
                raise
        chunks: list[bytes] = []
        size = 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                size += len(chunk)
                if size > maximum_bytes:
                    raise ValueError("Bybit private response exceeds maximum response bytes")
                chunks.append(chunk)
            return RawHttpResponse(
                status=int(response.status_code),
                headers={str(k).lower(): str(v) for k, v in response.headers.items()},
                content=b"".join(chunks),
            )
        finally:
            response.close()


class BybitPrivateHttpTransport:
    """Execute only signed, allowlisted private GET requests."""

    def __init__(
        self,
        backend: PrivateHttpBackend,
        *,
        environment: str,
        maximum_attempts: int = 3,
        maximum_retry_delay: float = 5.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        normalized = environment.strip().lower()
        if normalized not in PUBLIC_BASE_URLS:
            raise ValueError("Bybit private environment must be mainnet or testnet")
        if maximum_attempts < 1 or maximum_retry_delay < 0:
            raise ValueError("private retry configuration is invalid")
        self._base_url = PUBLIC_BASE_URLS[normalized]
        self._backend = backend
        self._maximum_attempts = int(maximum_attempts)
        self._maximum_retry_delay = float(maximum_retry_delay)
        self._sleep = sleep

    async def get(
        self,
        url: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
        *,
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> RawHttpResponse:
        path = self._validate_request(url, params, headers, timeout_seconds, maximum_bytes)
        normalized_params = {str(key): str(value) for key, value in params.items()}
        for attempt in range(1, self._maximum_attempts + 1):
            try:
                response = await self._backend.get(
                    url,
                    normalized_params,
                    dict(headers),
                    timeout_seconds=timeout_seconds,
                    maximum_bytes=maximum_bytes,
                )
            except (ConnectionError, TimeoutError):
                if attempt >= self._maximum_attempts:
                    raise
                await self._sleep(self._retry_delay(attempt, None))
                continue
            if len(response.content) > maximum_bytes:
                raise ValueError("Bybit private response exceeds maximum response bytes")
            response_headers = {
                str(key).lower(): str(value) for key, value in response.headers.items()
            }
            if response.status in TRANSIENT_STATUSES:
                if attempt >= self._maximum_attempts:
                    raise RuntimeError(
                        f"Bybit private transient HTTP {response.status} exhausted retries"
                    )
                await self._sleep(self._retry_delay(attempt, response_headers.get("retry-after")))
                continue
            if not 200 <= response.status < 300:
                raise RuntimeError(f"Bybit private HTTP {response.status}")
            if "application/json" not in response_headers.get("content-type", "").lower():
                raise ValueError("Bybit private response must use a JSON content type")
            try:
                payload = json.loads(response.content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Bybit private response contains invalid JSON") from exc
            if not isinstance(payload, Mapping):
                raise ValueError("Bybit private JSON root must be an object")
            try:
                code = int(payload.get("retCode", -1))
            except (TypeError, ValueError) as exc:
                raise ValueError("Bybit private retCode must be an integer") from exc
            if code == 10006:
                if attempt >= self._maximum_attempts:
                    raise RuntimeError("Bybit private API rate limit exhausted retries")
                await self._sleep(self._retry_delay(attempt, response_headers.get("retry-after")))
                continue
            if code != 0:
                raise ValueError(f"Bybit private API error {code}: {payload.get('retMsg', '')}")
            return response
        raise RuntimeError("Bybit private HTTP retry loop terminated unexpectedly")

    def _validate_request(
        self,
        url: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> str:
        if timeout_seconds <= 0 or maximum_bytes <= 0:
            raise ValueError("private request limits must be positive")
        parsed = urlsplit(url)
        expected = urlsplit(self._base_url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != expected.netloc
            or parsed.path not in PRIVATE_READ_PARAMETERS
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Bybit private URL is not allowlisted")
        if parsed.path != parsed.path.rstrip("/"):
            raise ValueError("Bybit private URL path is not canonical")
        allowed = PRIVATE_READ_PARAMETERS[parsed.path]
        normalized_params = {str(key): str(value) for key, value in params.items()}
        if set(normalized_params) - allowed:
            raise ValueError("Bybit private parameters are not allowlisted")
        if any(not key or not value for key, value in normalized_params.items()):
            raise ValueError("Bybit private parameters cannot be empty")
        if REQUIRED_PARAMETERS[parsed.path] - set(normalized_params):
            raise ValueError("Bybit private parameters are missing required fields")
        if parse_qsl(parsed.query):
            raise ValueError("Bybit private URL must not include an unsigned query")
        required_headers = {
            "x-bapi-api-key",
            "x-bapi-timestamp",
            "x-bapi-sign",
            "x-bapi-recv-window",
            "x-bapi-sign-type",
        }
        normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
        if not required_headers <= set(normalized_headers):
            raise ValueError("Bybit private signed headers are incomplete")
        if set(normalized_headers) - required_headers - {"accept"}:
            raise ValueError("Bybit private headers are not allowlisted")
        if normalized_headers.get("accept", "application/json") != "application/json":
            raise ValueError("Bybit private Accept header must be application/json")
        if not normalized_headers["x-bapi-api-key"] or not normalized_headers["x-bapi-sign"]:
            raise ValueError("Bybit private signed headers cannot be empty")
        return parsed.path

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None:
            try:
                requested = max(0.0, float(retry_after))
            except ValueError:
                requested = 0.25 * (2 ** (attempt - 1))
        else:
            requested = 0.25 * (2 ** (attempt - 1))
        return min(requested, self._maximum_retry_delay)
