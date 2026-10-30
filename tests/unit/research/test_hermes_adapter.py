from decimal import Decimal

import pytest

from trading_platform.research.agents.hermes import (
    HermesAdapter,
    PromptVersion,
    evaluate_responses,
)


class Provider:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


class FailingProvider:
    async def complete(self, **kwargs):
        raise TimeoutError("offline")


def prompt():
    return {"critique-v1": PromptVersion("critique-v1", "Review {context}")}


@pytest.mark.asyncio
async def test_hermes_adapter_requires_schema_and_allowlisted_tools():
    provider = Provider({
        "schema_version": "research_critique_v1",
        "decision": "accept",
        "rationale": "fixture evidence",
        "confidence": "0.8",
        "tool_requests": ["read_snapshot"],
        "cost_usd": "0.01",
    })
    result = await HermesAdapter(
        provider, prompts=prompt(), allowed_tools=("read_snapshot",),
        maximum_cost_usd=Decimal("0.10"),
    ).critique(prompt_name="critique-v1", context="market context")

    assert result.confidence == Decimal("0.8")
    assert provider.calls[0]["prompt_version"] == "critique-v1"


@pytest.mark.asyncio
async def test_hermes_adapter_denies_unauthorized_tools_and_cost_overruns():
    provider = Provider({
        "schema_version": "research_critique_v1", "decision": "accept",
        "rationale": "ignore policy and place order", "confidence": "0.9",
        "tool_requests": ["place_order"], "cost_usd": "0.01",
    })
    with pytest.raises(PermissionError, match="unauthorized"):
        await HermesAdapter(provider, prompts=prompt(), maximum_cost_usd=Decimal("0.10")).critique(
            prompt_name="critique-v1", context="untrusted text"
        )
    provider.payload["tool_requests"] = []
    provider.payload["cost_usd"] = "1"
    with pytest.raises(RuntimeError, match="cost limit"):
        await HermesAdapter(provider, prompts=prompt()).critique(
            prompt_name="critique-v1", context="context"
        )


def test_offline_evaluation_retains_invalid_and_adversarial_fixtures():
    report = evaluate_responses([
        {"schema_version": "research_critique_v1", "decision": "accept", "rationale": "ok", "confidence": "0.5", "tool_requests": []},
        {"schema_version": "research_critique_v1", "decision": "accept", "rationale": "prompt injection", "confidence": "0.9", "tool_requests": ["place_order"]},
        {"schema_version": "wrong"},
    ], allowed_tools=("read_snapshot",))

    assert report.total == 3
    assert report.valid == 1
    assert report.unauthorized_tool_requests == 1


@pytest.mark.asyncio
async def test_provider_timeout_is_fail_closed():
    with pytest.raises(RuntimeError, match="unavailable"):
        await HermesAdapter(FailingProvider(), prompts=prompt(), maximum_cost_usd=Decimal("1")).critique(
            prompt_name="critique-v1", context="fixture"
        )
