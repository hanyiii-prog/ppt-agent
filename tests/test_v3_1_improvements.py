"""Tests for v3.1 improvements: adaptive fonts, cover title, kit diversity."""
from __future__ import annotations

import pytest

from ppt_agent.page_kits import _adaptive_font_size
from ppt_agent.agent.pipeline import (
    _detect_content_kit,
    _diversify_kits,
    _coerce_design_plan,
)


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


class TestCoerceDesignPlan:
    def test_list_input_diversified(self):
        pages = [{"kit": "quad_cards"}, {"kit": "quad_cards"}, {"kit": "quad_cards"}]
        result = _coerce_design_plan(pages)
        assert len(result) == 3

    def test_dict_envelope(self):
        result = _coerce_design_plan({"pages": [{"kit": "quad_cards"}]})
        assert isinstance(result, list)
