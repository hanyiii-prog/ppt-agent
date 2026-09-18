"""Page Archetype selection tests."""

from __future__ import annotations

import pytest

from ppt_agent.content_ir import ContentBlock, ContentDocument
from ppt_agent.page_archetype import SCHEMA, annotate_plan, select_archetype
from ppt_agent.parsers import parse_markdown
from ppt_agent.presentation_plan import build_presentation_plan


def _bullets(*items: str) -> list[ContentBlock]:
    return [ContentBlock(type="bullets", id="b-1", items=list(items))]


def test_table_page_wins_over_everything() -> None:
    blocks = [
        ContentBlock(type="heading", id="h", text="指标", level=2),
        ContentBlock(type="table", id="t", headers=["a"], rows=[["1"]]),
        *_bullets("覆盖 5 个院区"),
    ]
    decision = select_archetype(blocks)
    assert decision["archetype"] == "table_page"
    assert decision["confidence"] >= 0.9


def test_timeline_from_ordered_date_items() -> None:
    blocks = [ContentBlock(type="ordered", id="o", items=[
        "9.11 完成数据治理", "9.30 完成接口联调", "10.15 完成全院培训",
    ])]
    assert select_archetype(blocks)["archetype"] == "timeline"


def test_comparison_needs_explicit_marker() -> None:
    blocks = _bullets("自建方案 vs 采购方案", "成本对比", "周期对比")
    assert select_archetype(blocks)["archetype"] == "comparison"


def test_metrics_row_from_hard_numbers() -> None:
    blocks = _bullets("数据抽取成功率 99.2%", "上线按期率 100%", "覆盖 5 个院区")
    assert select_archetype(blocks)["archetype"] == "metrics_row"


def test_cards_grid_from_parallel_bullets() -> None:
    blocks = _bullets("完成数据治理与清洗工作", "完成接口联调与压测工作",
                      "完成全院培训与演练工作", "完成应急预案的编制工作")
    decision = select_archetype(blocks)
    assert decision["archetype"] == "cards_grid"


def test_narrative_from_prose_only() -> None:
    blocks = [ContentBlock(type="paragraph", id="p", text="项目按期上线，四甲评审顺利通过。")]
    assert select_archetype(blocks)["archetype"] == "narrative"


def test_default_is_title_bullets() -> None:
    decision = select_archetype(_bullets("覆盖 5 个院区"))
    assert decision["archetype"] == "title_bullets"
    assert decision["schema"] == SCHEMA
    assert decision["reason"], "every decision must carry its reason"


def test_annotate_plan_stamps_content_pages_only(tmp_path) -> None:
    document = parse_markdown(
        "# 总结\n\n## 项目概况\n\n- 覆盖 5 个院区\n\n"
        "## 建设过程\n\n- 完成数据治理\n- 完成接口联调\n- 完成全院培训\n- 完成应急演练\n",
        source="sample.md",
    )
    plan = build_presentation_plan(document)
    annotated = annotate_plan(plan, document)
    # original untouched
    assert all("archetype" not in page for page in plan["pages"])
    kinds = {page["kind"]: page for page in annotated["pages"]}
    assert "archetype" in kinds["content"]
    assert "archetype" not in kinds["cover"]
    assert "archetype" not in kinds["closing"]
    assert annotated["metadata"]["archetypes"] == SCHEMA
