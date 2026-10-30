import asyncio
import json
import urllib.request
from typing import Any, Mapping

from trading_platform.research.agents.hermes import HermesProvider


class HttpHermesConnector(HermesProvider):
    """
    A concrete HTTP connector for external Hermes providers.
    Currently stubbed to prevent unauthorized external network calls and credential loading.
    """
    def __init__(self, endpoint_url: str):
        self._endpoint_url = endpoint_url

    async def complete(
        self, *, prompt: str, prompt_version: str, timeout_seconds: float
    ) -> Mapping[str, Any]:
        # This implementation will not execute actual network calls per Phase 12 rules:
        # "No external provider call or credential loading will be introduced."
        raise NotImplementedError("External network calls are disabled in Phase 12.")


class MockHermesProvider(HermesProvider):
    """
    A mock provider that replays predefined responses for offline benchmarking.
    """
    def __init__(self, responses: list[Mapping[str, Any]]):
        self._responses = list(responses)
        self._call_count = 0

    async def complete(
        self, *, prompt: str, prompt_version: str, timeout_seconds: float
    ) -> Mapping[str, Any]:
        if self._call_count >= len(self._responses):
            raise RuntimeError("Mock provider ran out of predefined responses")
        response = self._responses[self._call_count]
        self._call_count += 1
        return response
