from __future__ import annotations

from ppt_agent.agent.pipeline import (
    _blocks_to_steps,
    _ensure_story_spine,
    _plan_to_clone_pages,
)
from ppt_agent.content_ir import ContentBlock
from ppt_agent.parsers import parse_markdown


def test_progress_steps_consume_table_rows_and_preserve_status() -> None:
    table = ContentBlock(
        type="table",
        id="tbl-1",
        headers=["时间", "状态", "工作内容"],
        rows=[
            ["9 月", "已完成", "完成标签调研"],
            ["10 月", "进行中", "首批宽表交付"],
            ["12 月", "计划", "整体验收"],
        ],
    )

    steps = _blocks_to_steps([table])

    assert [step["date"] for step in steps] == ["9 月", "10 月", "12 月"]
    assert [step["status"] for step in steps] == ["done", "doing", "plan"]
    assert [step["title"] for step in steps] == [
        "完成标签调研",
        "首批宽表交付",
        "整体验收",
    ]


def test_section_page_derives_summary_from_following_content_pages() -> None:
    document = parse_markdown(
        "# 项目汇报\n\n"
        "## 建设背景\n\n"
        "调研已完成。\n\n"
        "## 总体方案\n\n"
        "形成双试点方案。\n"
    )
    headings = [block for block in document.blocks if block.type == "heading"]
    paragraphs = [block for block in document.blocks if block.type == "paragraph"]
    plan = {
        "pages": [
            {
                "kind": "cover",
                "title": "项目汇报",
                "source_blocks": [headings[0].id],
            },
            {
                "kind": "section",
                "title": "一、建设背景与方案",
                "source_blocks": [],
            },
            {
                "kind": "content",
                "title": "建设背景",
                "key_message": "调研已完成",
                "source_blocks": [headings[1].id, paragraphs[0].id],
            },
            {
                "kind": "content",
                "title": "总体方案",
                "key_message": "形成双试点方案",
                "source_blocks": [headings[2].id, paragraphs[1].id],
            },
            {
                "kind": "closing",
                "title": "谢谢",
                "source_blocks": [],
            },
        ]
    }

    pages = _plan_to_clone_pages(plan, document)
    sections = [page for page in pages if page["role"] == "section"]

    assert len(sections) == 1
    assert sections[0]["lines"] == ["调研已完成", "形成双试点方案"]


def test_content_page_selects_a_template_component_when_available() -> None:
    document = parse_markdown(
        "# 项目汇报\n\n## 组织保障\n\n- 院方统筹\n- 信息科保障\n- 卫宁执行\n- 临床验收\n"
    )
    headings = [block for block in document.blocks if block.type == "heading"]
    bullets = [block for block in document.blocks if block.type == "bullets"]
    plan = {
        "pages": [
            {
                "kind": "cover",
                "title": "项目汇报",
                "source_blocks": [headings[0].id],
            },
            {
                "kind": "content",
                "title": "组织保障",
                "key_message": "四方职责清晰",
                "source_blocks": [headings[1].id, bullets[0].id],
                "archetype": {"archetype": "responsibility"},
                "visual_kit": "org_chart",
            },
            {
                "kind": "closing",
                "title": "谢谢",
                "source_blocks": [],
            },
        ]
    }
    catalog = {
        "schema": "template-component-catalog/v1",
        "components": [{
            "component_id": "tpl-07-org_chart",
            "template_slide": 7,
            "page_kind": "content",
            "component_kind": "org_chart",
            "title": "项目组织保障",
            "tags": ["组织", "保障", "职责", "分工"],
            "slot_count": 6,
            "item_capacity": 4,
            "table_count": 0,
        }],
    }

    pages = _plan_to_clone_pages(plan, document, template_catalog=catalog)
    content = next(page for page in pages if page["role"] == "content")

    assert content["template_slide"] == 7
    assert content["template_component_id"] == "tpl-07-org_chart"


def test_story_spine_adds_toc_and_section_dividers() -> None:
    document = parse_markdown(
        "# 项目汇报\n\n"
        "## 建设背景\n\n背景内容。\n\n"
        "## 建设计划\n\n计划内容。\n"
    )
    headings = [block for block in document.blocks if block.type == "heading"]
    paragraphs = [block for block in document.blocks if block.type == "paragraph"]
    plan = {
        "pages": [
            {"kind": "cover", "title": "项目汇报", "source_blocks": [headings[0].id]},
            {
                "kind": "content",
                "title": "建设背景",
                "key_message": "背景已经明确",
                "source_blocks": [headings[1].id, paragraphs[0].id],
            },
            {
                "kind": "content",
                "title": "建设计划",
                "key_message": "计划分步推进",
                "source_blocks": [headings[2].id, paragraphs[1].id],
            },
            {"kind": "closing", "title": "谢谢", "source_blocks": []},
        ]
    }

    result = _ensure_story_spine(plan, document)
    kinds = [page["kind"] for page in result["pages"]]

    assert kinds == ["cover", "toc", "section", "content", "section", "content", "closing"]
    assert result["pages"][2]["lines"] == ["背景已经明确"]
    assert result["pages"][4]["lines"] == ["计划分步推进"]
