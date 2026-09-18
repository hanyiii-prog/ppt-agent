"""Narrative Engine tests: rules floor, LLM seam, honest degradation."""

from __future__ import annotations

import pytest

from ppt_agent.content_ir import ContentBlock, ContentDocument
from ppt_agent.narrative_engine import build_narrative
from ppt_agent.parsers import parse_markdown

SAMPLE = """# 上线总结

## 项目概况

- 覆盖 5 个院区

## 建设举措

- 完成数据治理

## 项目成效

- 数据抽取成功率 99.2%
- 四甲评审通过

## 下阶段重点

- 推进专病数据库建设
"""


@pytest.fixture(scope="module")
def document():
    return parse_markdown(SAMPLE, source="sample.md")


def test_rules_mode_discloses_llm_off(document) -> None:
    narrative = build_narrative(document)
    assert narrative["schema"] == "narrative/v1"
    assert narrative["mode"] == "rules"
    assert narrative["metadata"]["llm"] == "off"


def test_rules_arc_orders_business_stages(document) -> None:
    narrative = build_narrative(document)
    arc = narrative["arc"]
    titles = [entry for entry in arc]
    # context first, evidence before outlook
    assert titles.index("项目概况") < titles.index("项目成效") < titles.index("下阶段重点")


def test_sections_carry_stage_and_emphasis(document) -> None:
    narrative = build_narrative(document)
    by_title = {section["title"]: section for section in narrative["sections"]}
    assert by_title["项目概况"]["stage"] == "context"
    assert by_title["建设举措"]["stage"] == "action"
    assert by_title["项目成效"]["stage"] == "evidence"
    assert by_title["下阶段重点"]["stage"] == "outlook"
    assert by_title["项目成效"]["suggested_emphasis"] == "data"
    assert by_title["项目概况"]["suggested_emphasis"] == "narrative"


def test_llm_sampled_mode() -> None:
    document = ContentDocument(blocks=[
        ContentBlock(type="heading", id="h-1", text="项目概况", level=2),
        ContentBlock(type="heading", id="h-2", text="项目成效", level=2),
    ])

    def fake_llm(prompt: str) -> str:
        assert "项目概况" in prompt
        return "- 项目成效\n- 项目概况"

    narrative = build_narrative(document, llm_fn=fake_llm)
    assert narrative["metadata"]["llm"] == "sampled"
    assert narrative["arc"] == ["项目成效", "项目概况"]


def test_llm_failure_falls_back_and_discloses(document) -> None:
    def broken_llm(prompt: str) -> str:
        raise RuntimeError("sampling unavailable")

    narrative = build_narrative(document, llm_fn=broken_llm)
    assert narrative["mode"] == "rules"
    assert narrative["metadata"]["llm"] == "fallback"
    assert narrative["arc"], "fallback must still produce a full arc"


def test_llm_garbage_output_keeps_source_order(document) -> None:
    narrative = build_narrative(document, llm_fn=lambda prompt: "hallucinated nonsense")
    assert narrative["metadata"]["llm"] == "sampled"
    known = [block.text for block in document.headings()]
    assert [title for title in narrative["arc"] if title in known] == known
