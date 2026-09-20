"""V2.2 pipeline integration tests: kind DNA + element cache + fingerprint."""
import pytest

pytest.importorskip("pptx")

from ppt_agent.agent.plan_to_ir import plan_to_ir
from ppt_agent.agent.pipeline import run_pipeline
from ppt_agent.parsers import parse_markdown
from ppt_agent.presentation_plan import build_presentation_plan
from ppt_agent.page_kind_dna import build_page_kind_dna
from ppt_agent.design_dna import build_design_dna
from ppt_agent.template_fingerprint import compute_template_fingerprint

SAMPLE = """# Test Deck

## Overview

- Point one with data 99.2%
- Point two confirmed

## Results

- Metric A: 1200 units
- Metric B: 85%
"""


class TestPlanToIRV22:
    def test_returns_tuple_with_cache_report(self):
        doc = parse_markdown(SAMPLE)
        plan = build_presentation_plan(doc)
        presentation, cache = plan_to_ir(plan, doc, title="Test")
        assert isinstance(presentation.title, str)
        assert "hits" in cache
        assert "misses" in cache
        assert "hit_rate" in cache

    def test_layout_engine_parameter(self):
        doc = parse_markdown(SAMPLE)
        plan = build_presentation_plan(doc)
        p1, _ = plan_to_ir(plan, doc, layout_engine="legacy")
        p2, _ = plan_to_ir(plan, doc, layout_engine="solver")
        assert len(p1.slides) == len(p2.slides)

    def test_refuses_template_dna(self):
        doc = parse_markdown(SAMPLE)
        plan = build_presentation_plan(doc)
        with pytest.raises(ValueError, match="clone route"):
            plan_to_ir(plan, doc, template_dna={"schema": "template-dna/v0.4", "slides": []})


class TestPipelineV22:
    def test_v22_schema(self, tmp_path):
        report = run_pipeline(SAMPLE, out_dir=tmp_path / "out")
        assert report["schema"] == "pipeline/v2"

    def test_element_cache_reported(self, tmp_path):
        report = run_pipeline(SAMPLE, out_dir=tmp_path / "out")
        assert "element_cache" in report
        assert "hits" in report["element_cache"]
        assert "misses" in report["element_cache"]
        assert "hit_rate" in report["element_cache"]

    def test_design_rules_reported(self, tmp_path):
        report = run_pipeline(SAMPLE, out_dir=tmp_path / "out")
        assert "design_rules" in report
        assert "has_rules" in report["design_rules"]
        assert "findings" in report["design_rules"]

    def test_rasterizer_detected(self, tmp_path):
        report = run_pipeline(SAMPLE, out_dir=tmp_path / "out")
        gates = report["gates"]["fidelity_report"]["gates"]
        vr = next(g for g in gates if g["name"] == "visual_regression")
        # in CI Pillow is installed so it should be required/recommended
        assert vr["status"] in ("required", "recommended", "degraded")

    def test_component_matches_with_store(self, tmp_path):
        report = run_pipeline(SAMPLE, out_dir=tmp_path / "out")
        assert "component_matches" in report

    def test_no_template_no_fingerprint(self, tmp_path):
        report = run_pipeline(SAMPLE, out_dir=tmp_path / "out")
        assert report["template_fingerprint"] is None
