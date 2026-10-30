"""Transport-agnostic Telegram operator boundary.

This module only calls an injected application port. It has no broker imports,
credential loading, or direct access to trading state.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets
from typing import Any, Protocol

from trading_platform.domain.environment import TradingEnvironment

from .telegram_auth import OperatorRole, authorize


class OperatorApplicationPort(Protocol):
    async def execute_operator_action(
        self, *, action: str, parameters: Mapping[str, str], environment: TradingEnvironment
    ) -> Mapping[str, Any]: ...


class AuditSink(Protocol):
    def record(self, event: "OperatorAuditEvent") -> None: ...


@dataclass(frozen=True, slots=True)
class OperatorAuditEvent:
    user_id: str
    role: OperatorRole
    action: str
    environment: TradingEnvironment
    outcome: str
    occurred_at: datetime
    parameters: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.user_id.strip() or not self.action.strip():
            raise ValueError("operator audit identity must not be empty")
        if self.outcome not in {"accepted", "denied", "replayed", "expired", "failed"}:
            raise ValueError("operator audit outcome is invalid")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("operator audit timestamp must be timezone-aware")
        object.__setattr__(self, "parameters", dict(self.parameters))


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[OperatorAuditEvent] = []

    def record(self, event: OperatorAuditEvent) -> None:
        self.events.append(event)


class CallbackTokenCodec:
    """Sign short-lived, user-bound callback payloads with one-time nonces."""

    def __init__(
        self,
        secret: bytes | str,
        *,
        lifetime: timedelta = timedelta(minutes=2),
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        normalized = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
        if not normalized or lifetime <= timedelta(0):
            raise ValueError("callback secret and lifetime must be valid")
        self._secret = normalized
        self._lifetime = lifetime
        self._now = now
        self._used: set[str] = set()
        self._issued: dict[str, Mapping[str, Any]] = {}

    def issue(
        self,
        *,
        user_id: str,
        action: str,
        parameters: Mapping[str, str] = (),
    ) -> str:
        if not user_id.strip() or not action.strip():
            raise ValueError("callback identity must not be empty")
        issued = self._now()
        if issued.tzinfo is None or issued.utcoffset() is None:
            raise ValueError("callback clock must be timezone-aware")
        payload = {
            "user_id": user_id.strip(),
            "action": action.strip().lower(),
            "parameters": {str(key): str(value) for key, value in sorted(dict(parameters).items())},
            "nonce": secrets.token_hex(12),
            "expires_at": (issued + self._lifetime).isoformat(),
        }
        nonce = str(payload["nonce"])
        self._issued[nonce] = payload
        signature = hmac.new(self._secret, nonce.encode("ascii"), hashlib.sha256).hexdigest()[:32]
        return f"{nonce}.{signature}"

    def consume(self, token: str, *, user_id: str) -> Mapping[str, Any]:
        try:
            nonce, signature = token.split(".", 1)
            expected = hmac.new(self._secret, nonce.encode("ascii"), hashlib.sha256).hexdigest()[:32]
            if not hmac.compare_digest(signature, expected):
                raise PermissionError("callback signature is invalid")
            if nonce in self._used:
                raise RuntimeError("callback has already been consumed")
            payload = self._issued.get(nonce)
        except (ValueError, UnicodeError) as exc:
            raise PermissionError("callback token is malformed") from exc
        if not isinstance(payload, Mapping):
            raise PermissionError("callback token is unknown")
        if str(payload.get("user_id", "")) != user_id.strip():
            raise PermissionError("callback belongs to another user")
        nonce = str(payload.get("nonce", ""))
        if not nonce:
            raise RuntimeError("callback has already been consumed")
        try:
            expires = datetime.fromisoformat(str(payload["expires_at"]))
        except (KeyError, ValueError) as exc:
            raise PermissionError("callback expiry is invalid") from exc
        if expires.tzinfo is None or self._now() >= expires:
            raise TimeoutError("callback has expired")
        self._used.add(nonce)
        self._issued.pop(nonce, None)
        return payload


class TelegramOperatorConsole:
    def __init__(
        self,
        application: OperatorApplicationPort,
        callbacks: CallbackTokenCodec,
        audit: AuditSink,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._application = application
        self._callbacks = callbacks
        self._audit = audit
        self._now = now

    async def handle_callback(
        self,
        *,
        user_id: str,
        role: OperatorRole,
        environment: TradingEnvironment,
        token: str,
    ) -> Mapping[str, Any]:
        payload: Mapping[str, Any] | None = None
        outcome = "failed"
        try:
            payload = self._callbacks.consume(token, user_id=user_id)
            action = str(payload.get("action", ""))
            authorize(role, environment, action)
            parameters = payload.get("parameters", {})
            if not isinstance(parameters, Mapping):
                raise PermissionError("callback parameters must be an object")
            result = await self._application.execute_operator_action(
                action=action,
                parameters={str(key): str(value) for key, value in parameters.items()},
                environment=environment,
            )
            self._audit.record(
                OperatorAuditEvent(user_id, role, action, environment, "accepted", self._now(), parameters)
            )
            outcome = "accepted"
            return result
        except TimeoutError:
            outcome = "expired"
            raise
        except RuntimeError:
            outcome = "replayed"
            raise
        except PermissionError:
            outcome = "denied"
            raise
        except Exception:
            outcome = "failed"
            raise
        finally:
            if outcome != "accepted":
                self._audit.record(
                    OperatorAuditEvent(
                        user_id,
                        role,
                        str(payload.get("action", "unknown")) if payload is not None else "unknown",
                        environment,
                        outcome,
                        self._now(),
                        payload.get("parameters", {}) if payload is not None else {},
                    )
                )
