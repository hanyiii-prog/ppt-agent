"""Page Count Engine + Presentation Plan tests."""

from __future__ import annotations

import pytest

from ppt_agent.page_count import estimate_page_count
from ppt_agent.parsers import parse_markdown
from ppt_agent.presentation_plan import build_presentation_plan

SAMPLE = """# 口腔医院互联互通项目上线总结

## 项目概况

- 覆盖 5 个院区，服务 92 人团队
- 互联互通四甲评审通过
- 数据抽取成功率 99.2%

## 建设过程

- 完成数据治理与清洗
- 完成接口联调与压力测试
- 完成全院培训三轮
- 完成应急预案演练

## 下阶段重点

- 推进专病数据库建设，首批聚焦种植科与口腔癌
- 固化自动化部署流程，覆盖信创环境
"""


@pytest.fixture(scope="module")
def document():
    return parse_markdown(SAMPLE, source="sample.md")


def test_page_count_structure(document) -> None:
    estimate = estimate_page_count(document)
    assert estimate["schema"] == "page-count/v1"
    assert estimate["section_count"] == 3
    assert estimate["fixed_overhead"] == {"cover": 1, "toc": 1, "closing": 1}
    assert estimate["total"] == estimate["section_pages_total"] + 3
    assert estimate["assumptions"], "estimates must carry assumptions"


def test_page_count_density_moves_the_number(document) -> None:
    standard = estimate_page_count(document)["total"]
    compact = estimate_page_count(document, density="compact")["total"]
    air = estimate_page_count(document, density="air")["total"]
    assert compact <= standard <= air
    with pytest.raises(ValueError):
        estimate_page_count(document, density="luxury")


def test_plan_covers_all_kinds_in_order(document) -> None:
    plan = build_presentation_plan(document)
    assert plan["schema"] == "presentation-plan/v1"
    kinds = [page["kind"] for page in plan["pages"]]
    assert kinds[0] == "cover" and kinds[-1] == "closing"
    assert kinds.count("toc") == 1
    assert kinds.count("section") == 3
    assert all(page["title"] for page in plan["pages"] if page["kind"] == "section")
    assert plan["page_total"] == len(plan["pages"])


def test_plan_is_fully_traceable(document) -> None:
    plan = build_presentation_plan(document)
    block_ids = {block.id for block in document.blocks}
    planned_ids = {
        block_id
        for page in plan["pages"]
        for block_id in page["source_blocks"]
    }
    missing = block_ids - planned_ids
    # the cover title block may be consumed as the cover itself; everything else must be placed
    assert missing <= {document.blocks[0].id}
    page_numbers = [page["page_no"] for page in plan["pages"]]
    assert page_numbers == list(range(1, len(plan["pages"]) + 1))


def test_plan_metadata_discloses_no_llm(document) -> None:
    plan = build_presentation_plan(document)
    assert plan["metadata"]["llm"] == "off"
    assert plan["metadata"]["planner"] == "rules"


def test_plan_reconciles_with_estimate(document) -> None:
    plan = build_presentation_plan(document)
    estimate = estimate_page_count(document)
    assert abs(plan["page_total"] - estimate["total"]) <= 3, (
        "plan and estimate must stay within reconciliation tolerance"
    )
