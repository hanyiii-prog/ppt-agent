"""LLM provider layer (plan §7.1: host-delegated, zero local credentials).

ppt-agent never configures an API key or endpoint and never calls an external
LLM over HTTP. Every model call is *delegated to the calling host* through the
MCP sampling seam:

``MCPSamplingProvider``   -- real path: ``sampling/createMessage`` over the
                            server session (batch 3), timeout + retry owned
                            by the session.
``RuleFallbackProvider``  -- no-model heuristic planner; never raises.
``NullProvider``          -- scripted responses for tests/CI.

Honesty contract (execution red line 6): every consumer must surface which
path actually ran -- ``metadata.llm = sampled | fallback | off``. A degraded
run is never silent.
"""

from .provider import (
    ChatMessage,
    LLMProvider,
    LLMUnavailableError,
    MCPSamplingProvider,
    NullProvider,
    RuleFallbackProvider,
    llm_fn_from_provider,
    select_provider,
    sampling_supported,
)

__all__ = [
    "ChatMessage",
    "LLMProvider",
    "LLMUnavailableError",
    "MCPSamplingProvider",
    "NullProvider",
    "RuleFallbackProvider",
    "llm_fn_from_provider",
    "select_provider",
    "sampling_supported",
]
