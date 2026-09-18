"""Content Analyzer (rules) tests."""

from __future__ import annotations

import pytest

from ppt_agent.content_analyzer import analyze_content
from ppt_agent.content_ir import ContentBlock, ContentDocument
from ppt_agent.parsers import parse_markdown

SAMPLE = """# 上线总结

## 项目概况

- 覆盖 5 个院区
- 数据抽取成功率 99.2%

## 项目总结

顺利上线，四甲评审通过。
"""


@pytest.fixture(scope="module")
def parsed() -> ContentDocument:
    return parse_markdown(SAMPLE)


def test_analysis_enriches_every_block(parsed: ContentDocument) -> None:
    enriched = analyze_content(parsed)
    for block in enriched.blocks:
        assert "importance" in block.analysis
        assert "category" in block.analysis
        assert isinstance(block.analysis["keywords"], list)
        assert 0.0 <= block.analysis["importance"] <= 1.0


def test_analysis_is_non_destructive(parsed: ContentDocument) -> None:
    analyze_content(parsed)
    assert all(block.analysis == {} for block in parsed.blocks)
    assert "analyzer" not in parsed.metadata


def test_llm_stamp_is_off(parsed: ContentDocument) -> None:
    enriched = analyze_content(parsed)
    assert enriched.metadata["analyzer"] == "rules"
    assert enriched.metadata["llm"] == "off"


def test_structure_and_data_outrank_prose(parsed: ContentDocument) -> None:
    enriched = analyze_content(parsed)
    headings = [block for block in enriched.blocks if block.type == "heading"]
    table_like = [block for block in enriched.blocks if block.type == "bullets"]
    assert all(block.analysis["importance"] >= 0.7 for block in headings)
    metric_block = next(
        block for block in table_like
        if any("99.2%" in item for item in block.items)
    )
    assert metric_block.analysis["category"] == "metric"
    prose = next(block for block in enriched.blocks if block.type == "paragraph")
    assert prose.analysis["category"] == "narrative"


def test_keywords_extracted() -> None:
    block = ContentBlock(type="paragraph", id="p-1", text="数据抽取成功率 99.2%，接口联调完成")
    document = ContentDocument(blocks=[block])
    enriched = analyze_content(document)
    keywords = enriched.blocks[0].analysis["keywords"]
    assert keywords, "CJK bigram keywords must be extracted"
    assert any("数据" in keyword or "抽取" in keyword for keyword in keywords)
