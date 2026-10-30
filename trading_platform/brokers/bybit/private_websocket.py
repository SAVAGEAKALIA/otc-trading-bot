"""Injected, capability-limited Bybit private WebSocket session."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from typing import Any, Protocol

from trading_platform.execution.clock import Clock
from trading_platform.execution.order_manager import BrokerOrderSnapshot

from .private_dispatch import BybitPrivateStreamDispatcher
from .private_stream import PrivateStreamLifecycle


PRIVATE_WS_URLS = {
    "mainnet": "wss://stream.bybit.com/v5/private",
    "testnet": "wss://stream-testnet.bybit.com/v5/private",
}


def build_private_stream_auth(
    *, api_key: str, api_secret: str, expires_at_ms: int
) -> dict[str, object]:
    key = api_key.strip()
    secret = api_secret.encode("utf-8")
    if not key or not secret:
        raise ValueError("Bybit private stream credentials must not be empty")
    if expires_at_ms <= 0:
        raise ValueError("Bybit private stream expiry must be positive")
    payload = f"GET/realtime{expires_at_ms}"
    signature = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return {"op": "auth", "args": [key, expires_at_ms, signature]}


class BybitPrivateSocket(Protocol):
    async def send_json(self, payload: Mapping[str, object]) -> None: ...

    async def receive_json(self) -> Mapping[str, Any]: ...

    async def close(self) -> None: ...


class BybitPrivateConnector(Protocol):
    async def connect(self, url: str) -> BybitPrivateSocket: ...


class PrivateStreamReconciler(Protocol):
    async def reconcile(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class PrivateWebSocketConfig:
    auth_ttl: timedelta = timedelta(seconds=10)
    maximum_connect_attempts: int = 3
    heartbeat_interval: timedelta = timedelta(seconds=20)
    maximum_message_bytes: int = 5 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.auth_ttl <= timedelta(0):
            raise ValueError("auth_ttl must be positive")
        if self.maximum_connect_attempts < 1:
            raise ValueError("maximum_connect_attempts must be positive")
        if self.heartbeat_interval <= timedelta(0):
            raise ValueError("heartbeat_interval must be positive")
        if self.maximum_message_bytes <= 0:
            raise ValueError("maximum_message_bytes must be positive")


class BybitPrivateWebSocketSession:
    """Drive private-stream handshakes and events; never submits orders."""

    def __init__(
        self,
        connector: BybitPrivateConnector,
        *,
        lifecycle: PrivateStreamLifecycle,
        api_key: str,
        api_secret: str,
        environment: str,
        clock: Clock,
        reconciler: PrivateStreamReconciler,
        config: PrivateWebSocketConfig = PrivateWebSocketConfig(),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        normalized = environment.strip().lower()
        if normalized not in PRIVATE_WS_URLS:
            raise ValueError("Bybit private WebSocket environment must be mainnet or testnet")
        if not api_key.strip() or not api_secret:
            raise ValueError("Bybit private WebSocket credentials must not be empty")
        self._connector = connector
        self._lifecycle = lifecycle
        self._dispatcher = BybitPrivateStreamDispatcher(lifecycle)
        self._api_key = api_key.strip()
        self._api_secret = api_secret
        self._base_url = PRIVATE_WS_URLS[normalized]
        self._clock = clock
        self._reconciler = reconciler
        self._config = config
        self._sleep = sleep
        self._socket: BybitPrivateSocket | None = None
        self._reconciled_generation: int | None = None

    @property
    def generation(self) -> int:
        return self._lifecycle.generation

    async def connect(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self._config.maximum_connect_attempts + 1):
            try:
                socket = await self._connector.connect(self._base_url)
                self._socket = socket
                topics = self._lifecycle.connected_event()
                expires = int(
                    (self._clock.now() + self._config.auth_ttl).timestamp() * 1000
                )
                await socket.send_json(
                    build_private_stream_auth(
                        api_key=self._api_key,
                        api_secret=self._api_secret,
                        expires_at_ms=expires,
                    )
                )
                await self._expect_ack(socket, "auth")
                await socket.send_json({"op": "subscribe", "args": list(topics)})
                await self._expect_ack(socket, "subscribe")
                self._lifecycle.subscribed_event()
                self._reconciled_generation = None
                break
            except Exception as exc:
                last_error = exc
                self._reconciled_generation = None
                self._lifecycle.disconnected_event()
                if self._socket is not None:
                    await self._socket.close()
                self._socket = None
                if attempt < self._config.maximum_connect_attempts:
                    await self._sleep(0.25 * (2 ** (attempt - 1)))
        if self._socket is None:
            assert last_error is not None
            raise last_error
        if not await self._reconciler.reconcile():
            raise RuntimeError("Bybit private stream reconciliation did not pass")
        self._reconciled_generation = self._lifecycle.generation

    async def reconnect(self) -> None:
        await self.handle_disconnect()
        await self.connect()

    async def handle_disconnect(self) -> None:
        self._lifecycle.disconnected_event()
        self._reconciled_generation = None
        if self._socket is not None:
            await self._socket.close()
        self._socket = None

    async def reconcile_current_generation(self) -> None:
        if self._socket is None or not self._lifecycle.subscribed:
            raise RuntimeError("Bybit private stream must be connected before reconciliation")
        if not await self._reconciler.reconcile():
            raise RuntimeError("Bybit private stream reconciliation did not pass")
        self._reconciled_generation = self._lifecycle.generation

    async def heartbeat(self) -> None:
        socket = self._require_socket()
        try:
            await socket.send_json({"op": "ping"})
            payload = await socket.receive_json()
            if not isinstance(payload, Mapping):
                raise ValueError("Bybit private WebSocket heartbeat must be an object")
            if str(payload.get("op", "")).strip() != "ping":
                raise ValueError("Bybit private WebSocket heartbeat operation mismatch")
            if int(payload.get("retCode", -1)) != 0:
                raise ValueError("Bybit private WebSocket heartbeat failed")
            if str(payload.get("retMsg", "")).strip().lower() != "pong":
                raise ValueError("Bybit private WebSocket heartbeat acknowledgement is invalid")
        except Exception:
            self._reconciled_generation = None
            raise

    async def receive_once(self) -> BrokerOrderSnapshot:
        socket = self._require_socket()
        try:
            payload = await socket.receive_json()
            if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) > self._config.maximum_message_bytes:
                raise ValueError("Bybit private WebSocket message exceeds maximum bytes")
            snapshot = self._dispatcher.dispatch(payload)
            if not self._dispatcher.healthy():
                self._reconciled_generation = None
            return snapshot
        except Exception:
            self._reconciled_generation = None
            raise

    def submission_ready(self) -> bool:
        return (
            self._socket is not None
            and self._dispatcher.healthy()
            and self._reconciled_generation == self._lifecycle.generation
        )

    async def _expect_ack(self, socket: BybitPrivateSocket, operation: str) -> None:
        payload = await socket.receive_json()
        if not isinstance(payload, Mapping):
            raise ValueError("Bybit private WebSocket acknowledgement must be an object")
        if str(payload.get("op", "")).strip() != operation:
            raise ValueError("Bybit private WebSocket acknowledgement operation mismatch")
        try:
            ret_code = int(payload.get("retCode", -1))
        except (TypeError, ValueError) as exc:
            raise ValueError("Bybit private WebSocket acknowledgement code is invalid") from exc
        if ret_code != 0:
            raise ValueError(
                f"Bybit private WebSocket {operation} failed: {payload.get('retMsg', '')}"
            )

    def _require_socket(self) -> BybitPrivateSocket:
        if self._socket is None or not self._lifecycle.connected:
            raise RuntimeError("Bybit private WebSocket is not connected")
        return self._socket
