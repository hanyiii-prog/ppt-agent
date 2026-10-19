"""LLM provider tests: the honest-degradation contract (red line 6)."""

from __future__ import annotations

import queue
import json
import threading
import time

import pytest

from ppt_agent.llm import (
    ChatMessage,
    ImageAttachment,
    LLMUnavailableError,
    MCPSamplingProvider,
    NullProvider,
    RuleFallbackProvider,
    OpenAIResponsesProvider,
    configured_provider,
    llm_fn_from_provider,
    resolve_provider,
    sampling_supported,
    select_provider,
)
from ppt_agent.mcp.sampling import SamplingSession
from ppt_agent.narrative_engine import build_narrative
from ppt_agent.parsers import parse_markdown

SAMPLE = """# 上线总结

## 项目概况

- 覆盖 5 个院区

## 项目成效

- 四甲评审通过
"""


class FakeSession:
    """Scripted session for provider-level tests."""

    def __init__(self, *, supported: bool = True, result: dict | None = None,
                 error: Exception | None = None) -> None:
        self.supported = supported
        self.result = result
        self.error = error
        self.calls = 0

    def create_message(self, request: dict) -> dict:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result or {}


def _sampling_result(text: str) -> dict:
    return {"content": {"type": "text", "text": text}}


def test_null_provider_is_scripted() -> None:
    provider = NullProvider(response="固定回复")
    assert provider.chat([ChatMessage(role="user", content="anything")]) == "固定回复"


def test_rule_fallback_provider_echoes_actionable_lines() -> None:
    provider = RuleFallbackProvider()
    out = provider.chat([ChatMessage(role="user", content="请排序：\n- 项目概况\n- 项目成效\n说明文字")])
    assert out == "- 项目概况\n- 项目成效"


def test_sampling_supported_reads_handshake() -> None:
    assert sampling_supported({"sampling": {}})
    assert sampling_supported({"sampling": True})
    assert not sampling_supported({"tools": {}})
    assert not sampling_supported(None)


def test_mcp_provider_success_extracts_text() -> None:
    provider = MCPSamplingProvider(FakeSession(result=_sampling_result("- 项目成效\n- 项目概况")))
    assert provider.chat([ChatMessage(role="user", content="排一下")]) == "- 项目成效\n- 项目概况"


def test_mcp_provider_transport_failure_is_unavailable() -> None:
    provider = MCPSamplingProvider(FakeSession(error=RuntimeError("pipe broken")))
    with pytest.raises(LLMUnavailableError):
        provider.chat([ChatMessage(role="user", content="x")])


def test_mcp_provider_empty_response_is_unavailable() -> None:
    provider = MCPSamplingProvider(FakeSession(result={"content": {"type": "text", "text": "  "}}))
    with pytest.raises(LLMUnavailableError):
        provider.chat([ChatMessage(role="user", content="x")])


def test_mcp_provider_unsupported_session_raises() -> None:
    session = FakeSession(supported=False)
    provider = MCPSamplingProvider(session)
    with pytest.raises(LLMUnavailableError):
        provider.chat([ChatMessage(role="user", content="x")])
    assert session.calls == 0, "unsupported hosts must not be asked"


class _HTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.payload


def test_responses_provider_uses_configured_model_and_parses_output_text(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _HTTPResponse({"output_text": "storyboard"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenAIResponsesProvider(
        "https://api.example/v1/responses",
        "fresh-secret",
        "text-model",
        reasoning_effort="low",
    )

    result = provider.chat(
        [ChatMessage("user", "make a deck")],
        system="you are a planner",
        max_tokens=321,
    )

    request = captured["request"]
    body = json.loads(request.data)
    assert result == "storyboard"
    assert request.full_url == "https://api.example/v1/responses"
    assert request.get_header("Authorization") == "Bearer fresh-secret"
    assert body["model"] == "text-model"
    assert body["max_output_tokens"] == 321
    assert body["reasoning"] == {"effort": "low"}
    assert body["input"][0]["role"] == "system"
    assert body["input"][1]["content"][0] == {
        "type": "input_text",
        "text": "make a deck",
    }
    assert captured["timeout"] > 0
    assert "fresh-secret" not in repr(provider)


def test_responses_provider_routes_images_only_to_explicit_vision_model(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return _HTTPResponse({
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": "looks good"}],
            }],
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenAIResponsesProvider(
        "https://api.example/v1",
        "fresh-secret",
        "text-model",
        vision_model="vision-model",
    )
    assert provider.supports_vision
    assert provider.chat([ChatMessage(
        "user",
        "inspect",
        images=(ImageAttachment(b"image-bytes", "image/png"),),
    )]) == "looks good"

    body = captured["body"]
    assert body["model"] == "vision-model"
    image = body["input"][0]["content"][1]
    assert image["type"] == "input_image"
    assert image["image_url"].startswith("data:image/png;base64,")


def test_responses_provider_refuses_images_without_explicit_vision_model(monkeypatch) -> None:
    provider = OpenAIResponsesProvider(
        "https://api.example/v1/responses",
        "fresh-secret",
        "text-model",
    )
    called = False

    def fake_urlopen(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(LLMUnavailableError, match="vision_model_not_configured"):
        provider.chat([ChatMessage(
            "user", "inspect",
            images=(ImageAttachment(b"image-bytes", "image/png"),),
        )])
    assert not called


def test_responses_provider_sanitizes_transport_errors(monkeypatch) -> None:
    def fake_urlopen(*_args, **_kwargs):
        raise RuntimeError("request failed with fresh-secret")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenAIResponsesProvider(
        "https://api.example/v1/responses",
        "fresh-secret",
        "text-model",
    )
    with pytest.raises(LLMUnavailableError) as exc:
        provider.chat([ChatMessage("user", "hello")])
    assert "fresh-secret" not in str(exc.value)


def test_provider_configuration_prefers_direct_and_discloses_incomplete_config() -> None:
    direct, warning = configured_provider({
        "PPT_AGENT_API_BASE_URL": "https://api.example/v1/responses",
        "PPT_AGENT_API_KEY": "fresh-secret",
        "PPT_AGENT_MODEL": "text-model",
    })
    assert isinstance(direct, OpenAIResponsesProvider)
    assert not direct.supports_vision
    assert warning is None

    missing, warning = configured_provider({
        "PPT_AGENT_API_BASE_URL": "https://api.example/v1/responses",
        "PPT_AGENT_API_KEY": "fresh-secret",
    })
    assert missing is None
    assert "PPT_AGENT_MODEL" in warning
    assert "fresh-secret" not in warning


def test_provider_resolution_uses_sampling_when_direct_configuration_is_partial() -> None:
    session = FakeSession(supported=True, result=_sampling_result("host"))
    provider, warning = resolve_provider(
        session,
        environ={"PPT_AGENT_API_KEY": "fresh-secret"},
    )
    assert isinstance(provider, MCPSamplingProvider)
    # Host sampling wins; the partial direct config is not even attempted.
    assert warning is None


def test_select_provider_honesty() -> None:
    assert isinstance(select_provider(FakeSession(supported=True)), MCPSamplingProvider)
    assert select_provider(FakeSession(supported=False)) is None
    assert select_provider(None) is None


def test_narrative_via_provider_sampled_and_fallback() -> None:
    document = parse_markdown(SAMPLE)
    good = MCPSamplingProvider(FakeSession(result=_sampling_result("- 项目成效\n- 项目概况")))
    narrative = build_narrative(document, llm_fn=llm_fn_from_provider(good))
    assert narrative["metadata"]["llm"] == "sampled"
    # the LLM ordered two sections; the H1 title (cover material) trails
    assert narrative["arc"] == ["项目成效", "项目概况", "上线总结"]

    bad = MCPSamplingProvider(FakeSession(error=RuntimeError("timeout")))
    narrative = build_narrative(document, llm_fn=llm_fn_from_provider(bad))
    assert narrative["metadata"]["llm"] == "fallback"
    assert narrative["arc"], "fallback must keep the chain alive"


def test_provider_callable_has_an_explicit_vision_only_image_path() -> None:
    class RecordingProvider:
        name = "recording"
        supports_vision = True

        def __init__(self):
            self.messages = []

        def chat(self, messages, **_kwargs):
            self.messages.append(messages)
            return "ok"

    provider = RecordingProvider()
    call = llm_fn_from_provider(provider)
    image = ImageAttachment(b"image bytes", "image/jpeg")

    assert call("text prompt") == "ok"
    assert provider.messages[-1][0].images == ()
    assert call.with_images("visual prompt", [image]) == "ok"
    assert provider.messages[-1][0].images == (image,)

    text_only = llm_fn_from_provider(MCPSamplingProvider(
        FakeSession(result=_sampling_result("text only"))
    ))
    with pytest.raises(LLMUnavailableError, match="vision_not_declared"):
        text_only.with_images("visual prompt", [image])


def test_sampling_session_timeout_then_retry() -> None:
    received: list[dict] = []
    session = SamplingSession(
        lambda payload: received.append(payload),
        pump_fn=lambda timeout: (_ for _ in ()).throw(queue.Empty()),  # silence
        timeout_s=0.1,
        retries=1,
    )
    session.supported = True
    with pytest.raises(LLMUnavailableError):
        session.create_message({"messages": []})
    assert len(received) == 2, "retries=1 means exactly two attempts"


def test_sampling_session_delivers_by_id() -> None:
    received: list[dict] = []

    def pump(timeout: float) -> None:
        time.sleep(min(timeout, 0.01))  # never feeds; delivery happens via deliver_if_pending

    session = SamplingSession(lambda payload: received.append(payload), pump_fn=pump,
                              timeout_s=5.0, retries=0)
    session.supported = True
    answer: dict = {}

    def waiter() -> None:
        answer["result"] = session.create_message({"messages": []})

    thread = threading.Thread(target=waiter)
    thread.start()
    while not received:
        time.sleep(0.01)
    request_id = received[0]["id"]
    assert request_id < 0, "sampling ids must be negative (no collision with inbound)"
    session.deliver_if_pending({"jsonrpc": "2.0", "id": request_id, "result": _sampling_result("hi")})
    thread.join(timeout=2)
    assert answer["result"]["content"]["text"] == "hi"


def test_sampling_session_input_closed_is_unavailable() -> None:
    received: list[dict] = []

    def pump(timeout: float) -> None:
        raise LLMUnavailableError("host_closed_input")

    session = SamplingSession(lambda payload: received.append(payload), pump_fn=pump,
                              timeout_s=1.0, retries=2)
    session.supported = True
    with pytest.raises(LLMUnavailableError):
        session.create_message({"messages": []})
    assert len(received) == 1, "a closed stream must not be retried"


def test_sampling_session_without_support_never_writes() -> None:
    received: list[dict] = []
    session = SamplingSession(lambda payload: received.append(payload))
    assert session.supported is False
    with pytest.raises(LLMUnavailableError):
        session.create_message({})
    assert received == []
