"""LLM provider tests: the honest-degradation contract (red line 6)."""

from __future__ import annotations

import queue
import threading
import time

import pytest

from ppt_agent.llm import (
    ChatMessage,
    LLMUnavailableError,
    MCPSamplingProvider,
    NullProvider,
    RuleFallbackProvider,
    llm_fn_from_provider,
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
