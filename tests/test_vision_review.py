from __future__ import annotations

import base64
import json
from pathlib import Path

from PIL import Image

from ppt_agent.llm.provider import (
    ChatMessage,
    ImageAttachment,
    LLMUnavailableError,
    MCPSamplingProvider,
    sampling_vision_supported,
)
from ppt_agent.mcp.sampling import SamplingSession
from ppt_agent.mcp.server import handle_message
from ppt_agent.mcp.tools import ToolContext, tool_generate
from ppt_agent.visual_critic import ModelVisualCritic, review_pages


class FakeSession:
    supported = True
    vision_supported: bool | None = True

    def __init__(self, response: str):
        self.response = response
        self.requests: list[dict] = []

    def create_message(self, request: dict) -> dict:
        self.requests.append(request)
        return {"content": {"type": "text", "text": self.response}}


def _image(path: Path) -> Path:
    Image.new("RGB", (96, 54), "white").save(path)
    return path


def test_sampling_vision_capability_requires_explicit_declaration() -> None:
    assert sampling_vision_supported({
        "experimental": {"ppt-agent": {"samplingVision": True}},
    }) is True
    assert sampling_vision_supported({
        "experimental": {"ppt-agent": {"samplingVision": False}},
    }) is False
    assert sampling_vision_supported({"sampling": {"vision": True}}) is None
    assert sampling_vision_supported({}) is None


def test_mcp_initialize_records_explicit_vision_capability(tmp_path: Path) -> None:
    session = SamplingSession(lambda _payload: None)
    context = ToolContext(agent=object(), workspace=tmp_path, session=session)

    handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "capabilities": {
                    "sampling": {},
                    "experimental": {"ppt-agent": {"samplingVision": True}},
                },
            },
        },
        context=context,
    )

    assert session.supported
    assert session.vision_supported is True


def test_sampling_provider_serializes_image_content_only_for_visual_hosts() -> None:
    image = ImageAttachment(b"png-bytes", "image/png")
    session = FakeSession("ok")
    provider = MCPSamplingProvider(session)

    assert provider.supports_vision
    assert provider.chat(
        [ChatMessage("user", "Inspect this page", images=(image,))],
    ) == "ok"
    messages = session.requests[0]["messages"]
    assert messages[0]["content"] == {
        "type": "text",
        "text": "Inspect this page",
    }
    assert messages[1]["content"] == {
        "type": "image",
        "data": base64.b64encode(b"png-bytes").decode("ascii"),
        "mimeType": "image/png",
    }


def test_sampling_provider_refuses_undeclared_vision() -> None:
    session = FakeSession("ok")
    session.vision_supported = None
    provider = MCPSamplingProvider(session)

    assert not provider.supports_vision
    try:
        provider.chat([
            ChatMessage("user", "Inspect this page", images=(
                ImageAttachment(b"png-bytes", "image/png"),
            )),
        ])
    except LLMUnavailableError as exc:
        assert "vision" in str(exc)
    else:
        raise AssertionError("image input must not be sent without declared vision support")
    assert session.requests == []


def test_model_visual_critic_reviews_rendered_pages_and_parses_findings(tmp_path: Path) -> None:
    response = json.dumps({
        "slides": [{
            "page": 2,
            "findings": [{
                "severity": "warning",
                "rule": "dense_content",
                "message": "正文区域过于拥挤",
            }],
        }],
    }, ensure_ascii=False)
    session = FakeSession(response)
    critic = ModelVisualCritic(MCPSamplingProvider(session))

    findings = critic.review_deck([_image(tmp_path / "slide-2.png")])

    assert len(findings) == 1
    assert findings[0].page == 2
    assert findings[0].rule == "dense_content"
    sent = session.requests[0]["messages"]
    assert any(message["content"]["type"] == "image" for message in sent)
    assert "responseSchema" not in session.requests[0]
    assert "slides" in session.requests[0]["systemPrompt"]


def test_visual_review_falls_back_and_discloses_when_model_fails(tmp_path: Path) -> None:
    session = FakeSession("not-json")
    critic = ModelVisualCritic(MCPSamplingProvider(session))

    report = review_pages([_image(tmp_path / "slide.png")], critic)

    assert report.mode == "deterministic_fallback"
    assert "模型视觉审阅未完成" in (report.warning or "")
    assert report.to_dict()["mode"] == "deterministic_fallback"


def test_nonvisual_model_uses_deterministic_checks_with_user_warning(tmp_path: Path) -> None:
    report = review_pages(
        [_image(tmp_path / "slide.png")],
        fallback_reason="当前模型未声明视觉能力",
    )

    assert report.mode == "deterministic_fallback"
    assert report.warning == "当前模型未声明视觉能力"
    assert not report.passed
    assert report.pages[0].rule == "near_blank"


def test_generate_selects_visual_reviewer_only_when_host_declares_vision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict = {}

    def fake_pipeline(markdown: str, **kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr("ppt_agent.agent.pipeline.run_pipeline", fake_pipeline)
    session = FakeSession('{"schema":"storyboard/v1","slides":[]}')
    session.vision_supported = None
    context = ToolContext(agent=object(), workspace=tmp_path, session=session)

    tool_generate({"markdown": "# Report"}, context)

    assert captured["visual_critic"] is None
    assert "未声明" in captured["visual_review_reason"]

    session.vision_supported = True
    captured.clear()
    tool_generate({"markdown": "# Report"}, context)

    assert isinstance(captured["visual_critic"], ModelVisualCritic)
    assert captured["visual_review_reason"] is None

    session.vision_supported = False
    captured.clear()
    tool_generate({"markdown": "# Report"}, context)

    assert captured["visual_critic"] is None
    assert "不支持图像输入" in captured["visual_review_reason"]
