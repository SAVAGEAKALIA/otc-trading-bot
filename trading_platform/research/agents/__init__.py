"""Replaceable, non-authoritative research-agent provider contracts."""

from .hermes import (
    AgentEvaluation,
    HermesAdapter,
    PromptVersion,
    StructuredAgentResponse,
)

__all__ = ["AgentEvaluation", "HermesAdapter", "PromptVersion", "StructuredAgentResponse"]
