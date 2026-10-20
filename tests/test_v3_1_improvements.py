"""Tests for v3.1 improvements: adaptive fonts, cover title, kit diversity."""
from __future__ import annotations

import pytest

from ppt_agent.page_kits import _adaptive_font_size
from ppt_agent.agent.pipeline import (
    _detect_content_kit,
    _diversify_kits,
    _coerce_design_plan,
    _plan_to_clone_pages,
)
from ppt_agent.parsers import parse_markdown


class TestAdaptiveFontSize:
    def test_short_text_gets_bigger(self):
        # 20 chars in a 5.4x1.5in box at 10.5pt base -> should scale up
        result = _adaptive_font_size("短文本测试" * 4, 5.4, 1.5, 10.5)
        assert result > 10.5

    def test_dense_text_stays_same(self):
        text = "这是一段很长很长的中文文本，" * 30
        result = _adaptive_font_size(text, 5.4, 1.5, 10.5)
        assert result == 10.5

    def test_empty_text_returns_base(self):
        assert _adaptive_font_size("", 5.0, 1.0, 12.0) == 12.0

    def test_max_scale_cap(self):
        result = _adaptive_font_size("短", 10.0, 5.0, 10.0, max_scale=1.5)
        assert result <= 15.0


class TestDetectContentKit:
    def test_layer_detection(self):
        texts = ["第一层 数据底座", "第二层 汇聚入组", "第三层 模型存储", "第四层 业务服务", "第五层 科研应用"]
        assert _detect_content_kit(texts) == "stage_cards"

    def test_timeline_detection(self):
        texts = ["9月10日：专题会议", "9月上旬：调研完成", "9月中旬：模型设计"]
        assert _detect_content_kit(texts) == "progress_timeline"

    def test_numeric_detection(self):
        texts = ["质量控制通过率 96%", "字段完整度 99.1%"]
        assert _detect_content_kit(texts) == "quad_cards"

    def test_no_match_returns_none(self):
        texts = ["顶层指导方针", "以点带面跑通试点"]
        assert _detect_content_kit(texts) is None

    def test_comparison_requires_explicit_marker(self):
        texts = [
            "先讲边界，再讲动作：先明确合同、任务单、付款、工期和验收的边界。",
            "每个要求都落到证据：说明谁负责、何时完成、在哪里记录。",
            "区分制度与建议：历史文件与复盘材料只作补充。",
            "先识别适用范围：不同版本的适用范围存在差异。",
        ]
        assert _detect_content_kit(texts) is None


class TestVisualKitSelection:
    def test_visual_form_routes_comparison_to_two_panels(self):
        document = parse_markdown(
            "# Comparison\n\n"
            "- Current：Manual handoff creates delay\n"
            "- Proposal：Automated review creates traceability\n"
        )
        bullet = next(block for block in document.blocks if block.type == "bullets")
        pages = _plan_to_clone_pages({
            "pages": [{
                "kind": "content",
                "title": "Before and after",
                "source_blocks": [bullet.id],
                "visual_form": "左右对比",
            }],
        }, document)

        assert pages[0]["kit"] == "two_panel_list"
        assert pages[0]["left"]["rows"]
        assert pages[0]["right"]["rows"]

    def test_visual_form_routes_timeline_to_progress_timeline(self):
        document = parse_markdown(
            "# Rollout\n\n"
            "- 9月10日：专题会议\n"
            "- 9月20日：数据接入\n"
            "- 9月30日：上线验证\n"
        )
        bullet = next(block for block in document.blocks if block.type == "bullets")
        pages = _plan_to_clone_pages({
            "pages": [{
                "kind": "content",
                "title": "Rollout schedule",
                "source_blocks": [bullet.id],
                "visual_form": "时间轴推进",
            }],
        }, document)

        assert pages[0]["kit"] == "progress_timeline"
        assert pages[0]["steps"][0]["date"] == "9月10日"

    def test_visual_form_routes_matrix_to_editable_table(self):
        document = parse_markdown(
            "# Requirements\n\n"
            "| Capability | Phase | Owner |\n| --- | --- | --- |\n"
            "| Intake | P1 | Product |\n"
            "| Reporting | P2 | Analytics |\n"
            "| Audit | P2 | Security |\n"
        )
        table = next(block for block in document.blocks if block.type == "table")
        pages = _plan_to_clone_pages({
            "pages": [{
                "kind": "content",
                "title": "Requirements matrix",
                "source_blocks": [table.id],
                "visual_form": "矩阵表格",
            }],
        }, document)

        assert pages[0]["kit"] == "matrix_table"
        assert pages[0]["table"]["headers"] == ["Capability", "Phase", "Owner"]
        assert pages[0]["table"]["rows"][0] == ["Intake", "P1", "Product"]

    def test_table_page_semantics_select_matrix_table_without_request(self):
        document = parse_markdown(
            "# Requirements\n\n"
            "| Capability | Phase | Owner |\n| --- | --- | --- |\n"
            "| Intake | P1 | Product |\n"
            "| Reporting | P2 | Analytics |\n"
            "| Audit | P2 | Security |\n"
        )
        table = next(block for block in document.blocks if block.type == "table")
        pages = _plan_to_clone_pages({
            "pages": [{
                "kind": "content",
                "title": "Requirements matrix",
                "source_blocks": [table.id],
                "archetype": {"archetype": "table_page"},
            }],
        }, document)

        assert pages[0]["kit"] == "matrix_table"
        assert pages[0]["table"]["headers"] == ["Capability", "Phase", "Owner"]

    def test_large_table_page_splits_into_editable_matrix_tables(self):
        rows = "".join(f"| Item {i} | P1 | Owner {i} |\n" for i in range(1, 13))
        document = parse_markdown(
            "# Requirements\n\n"
            "| Capability | Phase | Owner |\n| --- | --- | --- |\n" + rows
        )
        table = next(block for block in document.blocks if block.type == "table")
        pages = _plan_to_clone_pages({
            "pages": [{
                "kind": "content",
                "title": "Requirements matrix",
                "source_blocks": [table.id],
                "archetype": {"archetype": "table_page"},
            }],
        }, document)

        assert [page["kit"] for page in pages] == ["matrix_table", "matrix_table"]
        assert pages[0]["title"].endswith("（1/2）")
        assert pages[1]["title"].endswith("（2/2）")
        assert len(pages[0]["table"]["rows"]) == 10
        assert len(pages[1]["table"]["rows"]) == 2
        assert pages[1]["table"]["rows"][0] == ["Item 11", "P1", "Owner 11"]

    def test_table_title_window_prevents_duplicate_rows_across_pages(self):
        rows = "".join(f"| {i} | Topic {i} | Owner {i} |\n" for i in range(1, 29))
        document = parse_markdown(
            "# Requirements\n\n"
            "| Page | Topic | Owner |\n| --- | --- | --- |\n" + rows
        )
        table = next(block for block in document.blocks if block.type == "table")
        pages = _plan_to_clone_pages({
            "pages": [
                {
                    "kind": "content",
                    "title": "Outline：1-14",
                    "source_blocks": [table.id],
                    "archetype": {"archetype": "table_page"},
                },
                {
                    "kind": "content",
                    "title": "Outline：15-28",
                    "source_blocks": [table.id],
                    "archetype": {"archetype": "table_page"},
                },
            ],
        }, document)

        assert [page["title"] for page in pages] == [
            "Outline：1-14（1/2）", "Outline：1-14（2/2）",
            "Outline：15-28（1/2）", "Outline：15-28（2/2）",
        ]
        assert pages[0]["table"]["rows"][0][0] == "1"
        assert pages[1]["table"]["rows"][-1][0] == "14"
        assert pages[2]["table"]["rows"][0][0] == "15"
        assert pages[3]["table"]["rows"][-1][0] == "28"

    def test_storyboard_row_ranges_materialize_only_selected_rows(self):
        rows = "".join(f"| {i} | Topic {i} | Owner {i} |\n" for i in range(1, 13))
        document = parse_markdown(
            "# Requirements\n\n"
            "| Page | Topic | Owner |\n| --- | --- | --- |\n" + rows
        )
        table = next(block for block in document.blocks if block.type == "table")
        pages = _plan_to_clone_pages({
            "pages": [{
                "kind": "content",
                "title": "Outline window",
                "source_blocks": [table.id],
                "visual_kit": "matrix_table",
                "table_row_ranges": [{"table_id": table.id, "start": 4, "end": 8}],
            }],
        }, document)

        assert len(pages) == 1
        assert pages[0]["kit"] == "matrix_table"
        assert [row[0] for row in pages[0]["table"]["rows"]] == ["4", "5", "6", "7", "8"]

    def test_architecture_semantics_select_layers_without_explicit_kit(self):
        document = parse_markdown(
            "# Platform\n\n## Architecture\n\n"
            "| Layer | Component | Purpose |\n| --- | --- | --- |\n"
            "| Data | Lakehouse | Stores source data |\n"
            "| Model | Feature service | Serves shared features |\n"
            "| App | Research portal | Supports researchers |\n"
        )
        table = next(block for block in document.blocks if block.type == "table")
        pages = _plan_to_clone_pages({
            "pages": [{
                "kind": "content",
                "title": "Platform architecture",
                "source_blocks": [table.id],
                "archetype": {"archetype": "architecture"},
            }],
        }, document)

        assert pages[0]["kit"] == "architecture_layers"

    def test_storyboard_architecture_kit_builds_editable_layers(self):
        document = parse_markdown(
            "# Platform\n\n## Architecture\n\n"
            "| Layer | Component | Purpose |\n| --- | --- | --- |\n"
            "| Data | Lakehouse | Stores source data |\n"
            "| Model | Feature service | Serves shared features |\n"
            "| App | Research portal | Supports researchers |\n"
        )
        table = next(block for block in document.blocks if block.type == "table")
        pages = _plan_to_clone_pages({
            "pages": [{
                "kind": "content",
                "title": "Platform architecture",
                "source_blocks": [table.id],
                "archetype": {"archetype": "architecture"},
                "visual_kit": "architecture_layers",
            }],
        }, document)

        assert pages[0]["kit"] == "architecture_layers"
        assert [layer["head"] for layer in pages[0]["layers"]] == [
            "Data", "Model", "App",
        ]
        assert pages[0]["layers"][1]["desc"] == "Feature service；Serves shared features"

    def test_responsibility_table_uses_role_cards_when_explicitly_selected(self):
        document = parse_markdown(
            "# Delivery\n\n## Responsibilities\n\n"
            "| Role | Owner | Duties |\n| --- | --- | --- |\n"
            "| Product | Team A | Prioritize roadmap |\n"
            "| Design | Team B | Define workflows |\n"
            "| Engineering | Team C | Build platform |\n"
            "| Operations | Team D | Run service |\n"
        )
        table = next(block for block in document.blocks if block.type == "table")
        pages = _plan_to_clone_pages({
            "pages": [{
                "kind": "content",
                "title": "Responsibilities",
                "source_blocks": [table.id],
                "archetype": {"archetype": "responsibility"},
                "visual_kit": "four_role_cards",
            }],
        }, document)

        assert pages[0]["kit"] == "four_role_cards"
        assert [card["name"] for card in pages[0]["cards"]] == [
            "Product", "Design", "Engineering", "Operations",
        ]
        assert pages[0]["cards"][0]["role"] == ""
        assert pages[0]["cards"][0]["duties"] == ["Owner: Team A", "Duties: Prioritize roadmap"]


class TestKitDiversity:
    def test_rotates_three_identical(self):
        pages = [
            {"kit": "quad_cards", "role": "content"},
            {"kit": "quad_cards", "role": "content"},
            {"kit": "quad_cards", "role": "content"},
        ]
        result = _diversify_kits(pages)
        assert result[2]["kit"] != "quad_cards"

    def test_preserves_two_identical(self):
        pages = [
            {"kit": "quad_cards", "role": "content"},
            {"kit": "quad_cards", "role": "content"},
            {"kit": "two_panel_list", "role": "content"},
        ]
        result = _diversify_kits(pages)
        assert result[0]["kit"] == "quad_cards"
        assert result[1]["kit"] == "quad_cards"
        assert result[2]["kit"] == "two_panel_list"

    def test_ignores_non_content_roles(self):
        pages = [
            {"role": "cover"},
            {"role": "toc"},
            {"role": "section"},
        ]
        result = _diversify_kits(pages)
        assert result == pages


class TestSparsePageGuards:
    def test_title_only_sections_derive_summary_instead_of_being_dropped(self):
        document = parse_markdown(
            "# Report\n\n## Results\n\n- Revenue reached 91%\n"
        )
        heading = next(block for block in document.blocks if block.type == "heading" and block.level == 2)
        bullet = next(block for block in document.blocks if block.type == "bullets")
        pages = _plan_to_clone_pages({
            "pages": [
                {"kind": "section", "title": "Results", "source_blocks": [heading.id]},
                {"kind": "content", "title": "Results", "source_blocks": [bullet.id]},
            ],
        }, document)

        assert [page["role"] for page in pages] == ["section", "content"]
        assert pages[0]["lines"] == ["Revenue reached 91%"]

    def test_one_sided_two_panel_falls_back_to_cards(self):
        document = parse_markdown(
            "# Report\n\n- Only one observation\n"
        )
        bullet = next(block for block in document.blocks if block.type == "bullets")
        pages = _plan_to_clone_pages({
            "pages": [{
                "kind": "content",
                "title": "Comparison",
                "source_blocks": [bullet.id],
                "visual_form": "左右对比",
            }],
        }, document)

        assert pages[0]["kit"] != "two_panel_list"
        assert "left" not in pages[0]
        assert "right" not in pages[0]


class TestCoerceDesignPlan:
    def test_list_input_diversified(self):
        pages = [{"kit": "quad_cards"}, {"kit": "quad_cards"}, {"kit": "quad_cards"}]
        result = _coerce_design_plan(pages)
        assert len(result) == 3

    def test_dict_envelope(self):
        result = _coerce_design_plan({"pages": [{"kit": "quad_cards"}]})
        assert isinstance(result, list)
