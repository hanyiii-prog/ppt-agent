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
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable
from urllib.parse import urlsplit, urlunsplit

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
    def provider_name(self) -> str:
        return self.name

    @property
    def model_name(self) -> str:
        return str(getattr(self.session, "model", "") or "宿主模型")

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


class OpenAIResponsesProvider:
    """Direct provider for OpenAI Responses-compatible endpoints.

    Credentials are held only in memory and are never included in repr output,
    response errors, or provider metadata. A separate vision model must be
    explicitly configured before image content is sent.
    """

    name = "openai-responses"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        vision_model: str | None = None,
        reasoning_effort: str | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        self.endpoint = _responses_endpoint(base_url)
        self._api_key = str(api_key).strip()
        self.model = str(model).strip()
        self.vision_model = str(vision_model or "").strip() or None
        self.reasoning_effort = str(reasoning_effort or "").strip().lower() or None
        self.timeout_s = max(1.0, float(timeout_s))
        if not self._api_key or not self.model:
            raise ValueError("api_key and model are required")
        if self.reasoning_effort not in {
            None, "none", "minimal", "low", "medium", "high", "xhigh",
        }:
            raise ValueError("unsupported reasoning_effort")

    @property
    def provider_name(self) -> str:
        return self.name

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def supports_vision(self) -> bool:
        return bool(self.vision_model)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(endpoint={self.endpoint!r}, "
            f"model={self.model!r}, vision_model={self.vision_model!r}, "
            "api_key=<redacted>)"
        )

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        has_images = any(message.images for message in messages)
        if has_images and not self.supports_vision:
            raise LLMUnavailableError("vision_model_not_configured")

        inputs: list[dict[str, Any]] = []
        if system:
            inputs.append({
                "role": "system",
                "content": [{"type": "input_text", "text": system}],
            })
        for message in messages:
            content: list[dict[str, str]] = []
            if message.content:
                content.append({"type": "input_text", "text": message.content})
            for image in message.images:
                if not image.mime_type.lower().startswith("image/"):
                    raise LLMUnavailableError("unsupported_image_mime_type")
                data = base64.b64encode(image.data).decode("ascii")
                content.append({
                    "type": "input_image",
                    "image_url": f"data:{image.mime_type};base64,{data}",
                })
            if content:
                inputs.append({"role": message.role, "content": content})

        payload: dict[str, Any] = {
            "model": self.vision_model if has_images else self.model,
            "input": inputs,
            "max_output_tokens": max(1, int(max_tokens)),
        }
        if self.reasoning_effort and self.reasoning_effort != "none":
            payload["reasoning"] = {"effort": self.reasoning_effort}

        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "ppt-agent/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise LLMUnavailableError(f"responses_http_{exc.code}") from None
        except Exception as exc:  # noqa: BLE001 -- endpoint failures must be sanitized
            raise LLMUnavailableError(
                f"responses_transport: {type(exc).__name__}"
            ) from None

        text = _responses_text(result)
        if not text:
            raise LLMUnavailableError("responses_empty_response")
        return text


def _responses_endpoint(base_url: str) -> str:
    """Normalize a service root, /v1 root, or full Responses URL."""
    try:
        parts = urlsplit(str(base_url).strip())
        if (
            parts.scheme not in {"https", "http"}
            or not parts.netloc
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise ValueError
        if parts.scheme == "http" and parts.hostname not in {
            "localhost", "127.0.0.1", "::1",
        }:
            raise ValueError
        path = parts.path.rstrip("/")
        if path.endswith("/responses"):
            endpoint_path = path
        elif path.endswith("/v1"):
            endpoint_path = path + "/responses"
        elif not path:
            endpoint_path = "/v1/responses"
        else:
            endpoint_path = path + "/v1/responses"
        return urlunsplit((parts.scheme, parts.netloc, endpoint_path, "", ""))
    except (TypeError, ValueError):
        raise ValueError(
            "base_url must be an HTTPS Responses endpoint without embedded credentials"
        ) from None


def _responses_text(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    output_text = result.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    chunks: list[str] = []
    output = result.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if (
                    isinstance(part, dict)
                    and part.get("type") in {"output_text", "text"}
                    and isinstance(part.get("text"), str)
                ):
                    chunks.append(part["text"])
    return "\n".join(part for part in chunks if part.strip()).strip()


def configured_provider(
    environ: dict[str, str] | None = None,
) -> tuple[OpenAIResponsesProvider | None, str | None]:
    """Read an optional direct Responses provider config without exposing secrets."""
    environment = os.environ if environ is None else environ
    names = {
        "base_url": "PPT_AGENT_API_BASE_URL",
        "api_key": "PPT_AGENT_API_KEY",
        "model": "PPT_AGENT_MODEL",
        "vision_model": "PPT_AGENT_VISION_MODEL",
        "reasoning_effort": "PPT_AGENT_REASONING_EFFORT",
    }
    values = {key: str(environment.get(name, "")).strip() for key, name in names.items()}
    if not any(values.values()):
        return None, None
    missing = [
        names[key] for key in ("base_url", "api_key", "model")
        if not values[key]
    ]
    if missing:
        return None, "直连模型配置不完整，缺少：" + "、".join(missing)
    try:
        provider = OpenAIResponsesProvider(
            values["base_url"],
            values["api_key"],
            values["model"],
            vision_model=values["vision_model"] or None,
            reasoning_effort=values["reasoning_effort"] or None,
        )
    except (TypeError, ValueError) as exc:
        return None, f"直连模型配置无效（{exc}）"
    return provider, None


class ChatCompletionsProvider:
    """Minimal OpenAI-compatible chat-completions client for fallback models."""

    name = "chat-completions-fallback"
    supports_vision = False

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout_s: float = 90.0,
    ) -> None:
        self.endpoint = _chat_completions_endpoint(base_url)
        self.model = model
        self._api_key = api_key
        self.timeout_s = timeout_s

    @property
    def provider_name(self) -> str:
        return self.name

    @property
    def model_name(self) -> str:
        return self.model

    def __repr__(self) -> str:
        return f"{type(self).__name__}(endpoint={self.endpoint!r}, model={self.model!r}, api_key=<redacted>)"

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        if any(message.images for message in messages):
            raise LLMUnavailableError("vision_model_not_configured")

        payload_messages: list[dict[str, str]] = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        for message in messages:
            if message.content:
                payload_messages.append({
                    "role": message.role,
                    "content": message.content,
                })

        payload = {
            "model": self.model,
            "messages": payload_messages,
            "max_tokens": max(1, int(max_tokens)),
        }
        import requests

        try:
            response = requests.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "ppt-agent/1.0",
                },
                json=payload,
                timeout=self.timeout_s,
            )
            if response.status_code >= 400:
                raise LLMUnavailableError(f"chat_completions_http_{response.status_code}")
            result = response.json()
        except LLMUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 -- fallback endpoint failures stay sanitized
            raise LLMUnavailableError(
                f"chat_completions_transport: {type(exc).__name__}"
            ) from None

        text = _chat_completions_text(result)
        if not text:
            raise LLMUnavailableError("chat_completions_empty_response")
        return text


def _chat_completions_endpoint(base_url: str) -> str:
    try:
        parts = urlsplit(str(base_url).strip())
        if (
            parts.scheme not in {"https", "http"}
            or not parts.netloc
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise ValueError
        if parts.scheme == "http" and parts.hostname not in {
            "localhost", "127.0.0.1", "::1",
        }:
            raise ValueError
        path = parts.path.rstrip("/")
        if path.endswith("/chat/completions"):
            endpoint_path = path
        elif path.endswith("/v1"):
            endpoint_path = path + "/chat/completions"
        elif not path:
            endpoint_path = "/v1/chat/completions"
        else:
            endpoint_path = path + "/v1/chat/completions"
        return urlunsplit((parts.scheme, parts.netloc, endpoint_path, "", ""))
    except (TypeError, ValueError):
        raise ValueError(
            "fallback base_url must be an HTTPS chat-completions endpoint without embedded credentials"
        ) from None


def _chat_completions_text(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    choices = result.get("choices")
    if not isinstance(choices, list):
        return ""
    first = choices[0] if choices else None
    message = first.get("message") if isinstance(first, dict) else None
    text = message.get("content") if isinstance(message, dict) else None
    return text.strip() if isinstance(text, str) else ""


def configured_fallback_providers(
    environ: dict[str, str] | None = None,
) -> tuple[list[ChatCompletionsProvider], str | None]:
    """Read an optional OpenAI-compatible fallback model chain."""
    environment = os.environ if environ is None else environ
    names = {
        "base_url": "PPT_AGENT_FALLBACK_API_BASE_URL",
        "api_key": "PPT_AGENT_FALLBACK_API_KEY",
        "models": "PPT_AGENT_FALLBACK_MODELS",
    }
    values = {key: str(environment.get(name, "")).strip() for key, name in names.items()}
    if not any(values.values()):
        return [], None
    missing = [names[key] for key in ("base_url", "api_key", "models") if not values[key]]
    if missing:
        return [], "兜底模型配置不完整，缺少：" + "、".join(missing)
    models = [item.strip() for item in values["models"].split(",") if item.strip()]
    if not models:
        return [], "兜底模型列表为空"
    try:
        providers = [
            ChatCompletionsProvider(values["base_url"], values["api_key"], model)
            for model in models
        ]
    except (TypeError, ValueError) as exc:
        return [], f"兜底模型配置无效（{exc}）"
    return providers, None


class FallbackProvider:
    """Try the primary provider first, then an explicit fallback chain."""

    def __init__(self, primary: LLMProvider, fallbacks: list[LLMProvider] | tuple[LLMProvider, ...]) -> None:
        self.primary = primary
        self.fallbacks = tuple(fallbacks)
        self.name = f"{primary.name}+fallback"
        self.supports_vision = getattr(primary, "supports_vision", False) is True
        self._last_provider_name = str(getattr(primary, "provider_name", primary.name))
        self._last_model_name = str(getattr(primary, "model_name", "") or "宿主模型")

    @property
    def provider_name(self) -> str:
        return self._last_provider_name

    @property
    def model_name(self) -> str:
        return self._last_model_name

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(primary={self.primary.name!r}, "
            f"fallbacks={[provider.name for provider in self.fallbacks]})"
        )

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        last_error: LLMUnavailableError | None = None
        candidates = (self.primary, *self.fallbacks)
        for provider in candidates:
            try:
                text = provider.chat(
                    messages,
                    system=system,
                    max_tokens=max_tokens,
                    response_schema=response_schema,
                )
                self._last_provider_name = str(getattr(provider, "provider_name", provider.name))
                self._last_model_name = str(getattr(provider, "model_name", "") or provider.name)
                return text
            except LLMUnavailableError as exc:
                last_error = exc
        raise last_error or LLMUnavailableError("fallback_unavailable")


def resolve_provider(
    session: Any,
    *,
    environ: dict[str, str] | None = None,
) -> tuple[LLMProvider | None, str | None]:
    """Prefer the host's Sampling model, then a direct API provider.

    The design intent is that MCP callers get *the conversation's own model*
    by default (via ``sampling/createMessage``). A direct provider configured
    through ``PPT_AGENT_API_*`` env vars is a fallback for hosts that do not
    declare sampling support -- not an override.
    """
    host = select_provider(session)
    if host is not None:
        fallbacks, fallback_warning = configured_fallback_providers(environ)
        if fallbacks:
            return FallbackProvider(host, fallbacks), fallback_warning
        return host, fallback_warning
    direct, direct_warning = configured_provider(environ)
    fallbacks, fallback_warning = configured_fallback_providers(environ)
    if direct is not None:
        if fallbacks:
            return FallbackProvider(direct, fallbacks), fallback_warning
        return direct, direct_warning
    if fallbacks:
        warning = fallback_warning or "未配置直连主模型，使用兜底模型"
        if len(fallbacks) == 1:
            return fallbacks[0], warning
        return FallbackProvider(fallbacks[0], fallbacks[1:]), warning
    return None, direct_warning or fallback_warning


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


class ProviderLLMFunction:
    """Callable text adapter with an explicit, capability-checked image path."""

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider
        self.supports_vision = getattr(provider, "supports_vision", False) is True

    def __call__(self, prompt: str) -> str:
        return self.provider.chat(
            [ChatMessage(role="user", content=prompt)],
            max_tokens=2048,
        )

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        return self.provider.chat(
            messages,
            system=system,
            max_tokens=max_tokens,
            response_schema=response_schema,
        )

    def with_images(
        self,
        prompt: str,
        images: list[ImageAttachment] | tuple[ImageAttachment, ...],
    ) -> str:
        if not self.supports_vision:
            raise LLMUnavailableError("vision_not_declared")
        return self.provider.chat(
            [ChatMessage(role="user", content=prompt, images=tuple(images))],
            max_tokens=8192,
        )


def llm_fn_from_provider(provider: LLMProvider) -> ProviderLLMFunction:
    """Adapt a provider to text and explicitly supported multimodal calls."""
    return ProviderLLMFunction(provider)


# --- vision capability probe ------------------------------------------------
# A declared capability is not a working capability: the probe sends a known
# image and verifies the answer, so a text-only model behind a vision config
# fails loudly here instead of silently degrading the aesthetic pipeline.

_PROBE_SIZE = 48  # px square; tiny on purpose -- cheap and fast


def _probe_image(color: tuple[int, int, int]) -> ImageAttachment:
    import io as _io

    from PIL import Image as _Image

    img = _Image.new("RGB", (_PROBE_SIZE, _PROBE_SIZE), color)
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    return ImageAttachment(data=buf.getvalue(), mime_type="image/png")


def probe_vision_capability(
    provider: LLMProvider,
    *,
    attempts: int = 2,
) -> tuple[bool, str | None]:
    """Actively verify that ``provider`` can actually see images.

    Sends a solid-colour test image and checks the answer. Returns
    ``(ok, detail)``. ``ok`` is True only when the model answers correctly
    on at least one of ``attempts`` rounds with different colours, which
    rules out a text-only model that echoes a canned phrase.
    """
    llm = llm_fn_from_provider(provider)
    if not llm.supports_vision:
        return False, "provider_declares_no_vision"
    cases = [((224, 27, 33), "red"), ((20, 90, 200), "blue")]
    colors = cases[: max(1, int(attempts))]
    answered_any = False
    last_error: str | None = None
    for rgb, expected in colors:
        try:
            reply = llm.with_images(
                "这张图片是什么颜色？请只回答颜色英文名，如 red/blue/green。",
                [_probe_image(rgb)],
            )
        except LLMUnavailableError as exc:
            last_error = str(exc)
            continue
        except Exception as exc:  # noqa: BLE001 -- probe must not crash the pipeline
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        text = (reply or "").strip().lower()
        if expected in text:
            answered_any = True
        else:
            last_error = f"expected {expected!r}, got {text[:80]!r}"
    if answered_any:
        return True, None
    return False, last_error or "vision_probe_failed"
