"""Strict offline contract for optional Hermes-style research providers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Any, Protocol


class HermesProvider(Protocol):
    async def complete(
        self, *, prompt: str, prompt_version: str, timeout_seconds: float
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class PromptVersion:
    name: str
    template: str
    output_schema: str = "research_critique_v1"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", self.name.strip()):
            raise ValueError("prompt version name is not portable")
        if not self.template.strip() or not self.output_schema.strip():
            raise ValueError("prompt version fields must not be empty")


@dataclass(frozen=True, slots=True)
class StructuredAgentResponse:
    decision: str
    rationale: str
    confidence: Decimal
    tool_requests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        decision = self.decision.strip().lower()
        if decision not in {"accept", "reject", "abstain"}:
            raise ValueError("agent decision must be accept, reject, or abstain")
        if not self.rationale.strip():
            raise ValueError("agent rationale must not be empty")
        if not self.confidence.is_finite() or not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("agent confidence must be in [0, 1]")
        if any(not item.strip() for item in self.tool_requests):
            raise ValueError("agent tool request names must not be empty")
        object.__setattr__(self, "decision", decision)


@dataclass(frozen=True, slots=True)
class AgentEvaluation:
    total: int
    valid: int
    unauthorized_tool_requests: int
    average_confidence: Decimal

    @property
    def accuracy_proxy(self) -> Decimal:
        return Decimal(self.valid) / Decimal(self.total) if self.total else Decimal("0")


class HermesAdapter:
    """Inject a provider; this adapter owns parsing, limits and tool denial."""

    def __init__(
        self,
        provider: HermesProvider,
        *,
        prompts: Mapping[str, PromptVersion],
        allowed_tools: Sequence[str] = (),
        timeout_seconds: float = 10.0,
        maximum_cost_usd: Decimal = Decimal("0"),
        cost_estimator: Callable[[Mapping[str, Any]], Decimal] | None = None,
    ) -> None:
        if timeout_seconds <= 0 or not maximum_cost_usd.is_finite() or maximum_cost_usd < 0:
            raise ValueError("agent limits are invalid")
        self._provider = provider
        self._prompts = dict(prompts)
        self._allowed_tools = frozenset(item.strip() for item in allowed_tools if item.strip())
        self._timeout_seconds = timeout_seconds
        self._maximum_cost_usd = maximum_cost_usd
        self._cost_estimator = cost_estimator or (lambda payload: Decimal(str(payload.get("cost_usd", "0"))))

    async def critique(self, *, prompt_name: str, context: str) -> StructuredAgentResponse:
        try:
            prompt = self._prompts[prompt_name]
        except KeyError as exc:
            raise ValueError("prompt version is not registered") from exc
        if not context.strip():
            raise ValueError("agent context must not be empty")
        try:
            payload = await self._provider.complete(
                prompt=prompt.template.replace("{context}", context),
                prompt_version=prompt.name,
                timeout_seconds=self._timeout_seconds,
            )
        except (TimeoutError, ConnectionError) as exc:
            raise RuntimeError("agent provider unavailable") from exc
        response = self._parse(payload)
        cost = self._cost_estimator(payload)
        if not cost.is_finite() or cost < 0 or cost > self._maximum_cost_usd:
            raise RuntimeError("agent cost limit exceeded")
        unauthorized = set(response.tool_requests) - self._allowed_tools
        if unauthorized:
            raise PermissionError("agent requested an unauthorized tool")
        return response

    def _parse(self, payload: Mapping[str, Any]) -> StructuredAgentResponse:
        if not isinstance(payload, Mapping) or payload.get("schema_version") != "research_critique_v1":
            raise ValueError("agent response schema is invalid")
        raw_tools = payload.get("tool_requests", ())
        if not isinstance(raw_tools, (list, tuple)):
            raise ValueError("agent tool_requests must be an array")
        return StructuredAgentResponse(
            str(payload.get("decision", "")),
            str(payload.get("rationale", "")),
            Decimal(str(payload.get("confidence", "-1"))),
            tuple(str(item) for item in raw_tools),
        )


def evaluate_responses(
    responses: Sequence[Mapping[str, Any]], *, allowed_tools: Sequence[str] = ()
) -> AgentEvaluation:
    valid = 0
    unauthorized = 0
    confidence = Decimal("0")
    allowed = set(allowed_tools)
    for payload in responses:
        try:
            parsed = HermesAdapter._parse(HermesAdapter.__new__(HermesAdapter), payload)
            unauthorized += len(set(parsed.tool_requests) - allowed)
            if not (set(parsed.tool_requests) - allowed):
                valid += 1
            confidence += parsed.confidence
        except (TypeError, ValueError):
            continue
    total = len(responses)
    return AgentEvaluation(total, valid, unauthorized, confidence / Decimal(valid) if valid else Decimal("0"))
