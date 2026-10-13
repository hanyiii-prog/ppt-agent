"""LLM providers: the host-delegated sampling path plus its honest fallbacks.

``MCPSamplingProvider``
    Speaks ``sampling/createMessage`` through a *sampling session* (see
    ``ppt_agent.mcp.sampling``). The session owns timeout and retry; the
    provider owns request/response shaping and raises ``LLMUnavailableError``
    on any transport or shape failure so consumers can degrade explicitly.

``RuleFallbackProvider``
    A deterministic, no-model planner: it re-emits the bullet/heading lines
    found in the last user message as the plan. It is *not* a model and never
    pretends to be one -- consumers must still label their output ``fallback``
    or ``off`` when the rules path (not this provider) did the planning.

``NullProvider``
    Scripted text for tests and CI. Zero I/O, zero nondeterminism.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

_BULLET_LINE = re.compile(r"^\s*(?:[-*•·]|\d+[.)、])\s*(.+)$")


class LLMUnavailableError(RuntimeError):
    """Raised when sampling is unsupported, times out, or returns garbage."""


@dataclass(frozen=True)
class ChatMessage:
    role: str            # "user" | "assistant"
    content: str
    images: tuple["ImageAttachment", ...] = ()


@dataclass(frozen=True)
class ImageAttachment:
    data: bytes
    mime_type: str


@runtime_checkable
class LLMProvider(Protocol):
    """The single seam every LLM consumer talks to."""

    name: str

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        ...  # pragma: no cover - protocol


def sampling_supported(client_capabilities: dict[str, Any] | None) -> bool:
    """Read a client ``initialize`` capabilities dict for the sampling flag."""
    if not isinstance(client_capabilities, dict):
        return False
    sampling = client_capabilities.get("sampling")
    if isinstance(sampling, dict):
        return True
    return sampling is True


def sampling_vision_supported(client_capabilities: dict[str, Any] | None) -> bool | None:
    """Read the ppt-agent vision extension; sampling alone does not imply vision."""
    if not isinstance(client_capabilities, dict):
        return None
    experimental = client_capabilities.get("experimental")
    if not isinstance(experimental, dict):
        return None
    ppt_agent = experimental.get("ppt-agent")
    if not isinstance(ppt_agent, dict):
        return None
    vision = ppt_agent.get("samplingVision")
    return vision if isinstance(vision, bool) else None


class MCPSamplingProvider:
    """Host-delegated model access via the MCP sampling session."""

    name = "mcp-sampling"

    def __init__(self, session: Any) -> None:
        # session: ppt_agent.mcp.sampling.SamplingSession (typed loosely to
        # keep the llm package importable without the mcp package)
        self.session = session

    @property
    def supports_vision(self) -> bool:
        return getattr(self.session, "vision_supported", None) is True

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        # pre-check: an unsupported host must never be asked at all
        if not getattr(self.session, "supported", False):
            raise LLMUnavailableError("host_without_sampling")
        if any(message.images for message in messages) and not self.supports_vision:
            raise LLMUnavailableError("host_vision_not_declared")
        serialized_messages: list[dict[str, Any]] = []
        for message in messages:
            if message.content:
                serialized_messages.append({
                    "role": message.role,
                    "content": {"type": "text", "text": message.content},
                })
            for image in message.images:
                serialized_messages.append({
                    "role": message.role,
                    "content": {
                        "type": "image",
                        "data": base64.b64encode(image.data).decode("ascii"),
                        "mimeType": image.mime_type,
                    },
                })
        request: dict[str, Any] = {
            "messages": serialized_messages,
            "maxTokens": int(max_tokens),
        }
        if system:
            request["systemPrompt"] = system
        if response_schema:
            request["responseSchema"] = response_schema
        try:
            result = self.session.create_message(request)
        except LLMUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 -- any transport failure degrades
            raise LLMUnavailableError(f"sampling_transport: {type(exc).__name__}: {exc}") from exc
        content = (result or {}).get("content") or {}
        text = content.get("text") if isinstance(content, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise LLMUnavailableError("sampling_empty_response")
        return text


class RuleFallbackProvider:
    """Structure-heuristic planner: echoes the actionable lines in the prompt.

    It performs no inference. It exists so a caller that insists on holding a
    provider object still gets *deterministic* behaviour without a model --
    the honest label for anything produced this way is still ``fallback``.
    """

    name = "rules"

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        last_user = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        lines: list[str] = []
        for line in last_user.splitlines():
            match = _BULLET_LINE.match(line)
            if match:
                text = match.group(1).strip()
                if text:
                    lines.append(f"- {text}")
        return "\n".join(lines)


class NullProvider:
    """Scripted response for tests and CI. Zero I/O, zero nondeterminism."""

    name = "null"

    def __init__(self, response: str = "OK") -> None:
        self.response = response

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        return self.response


def select_provider(session: Any) -> LLMProvider | None:
    """Pick the provider for a server session.

    Returns ``MCPSamplingProvider`` when the host declared sampling support;
    ``None`` when it did not -- ``None`` means *no LLM was attempted* and the
    consumer must label its output ``off``, never silently ``fallback``.
    """
    if session is not None and getattr(session, "supported", False):
        return MCPSamplingProvider(session)
    return None


def llm_fn_from_provider(provider: LLMProvider) -> Callable[[str], str]:
    """Adapt a provider to the ``llm_fn`` seam narrative_engine consumes."""

    def llm_fn(prompt: str) -> str:
        return provider.chat(
            [ChatMessage(role="user", content=prompt)],
            max_tokens=2048,
        )

    return llm_fn
