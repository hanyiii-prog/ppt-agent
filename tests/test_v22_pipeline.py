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

    def test_designed_dark_page_uses_light_title_and_drops_duplicate_heading(self):
        doc = parse_markdown("# Report\n\n## Results\n\n- Adoption reached 82%")
        heading = next(block for block in doc.blocks if block.type == "heading" and block.level == 2)
        plan = {
            "pages": [
                {
                    "page_no": 1,
                    "kind": "cover",
                    "title": "Report",
                    "source_blocks": [doc.blocks[0].id],
                },
                {
                    "page_no": 2,
                    "kind": "content",
                    "title": "Results",
                    "source_blocks": [heading.id],
                },
            ],
        }

        presentation, _cache = plan_to_ir(plan, doc)

        cover_title = presentation.slides[0].components[0]
        assert cover_title.style["font"]["rgb"] == "FFFFFF"
        body_slide = presentation.slides[1]
        assert sum(component.text == "Results" for component in body_slide.components) == 1


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

    def test_model_storyboard_drives_page_plan_and_receives_task_constraints(self, tmp_path):
        from ppt_agent.parsers import parse_markdown

        source = "# Report\n\n## Results\n\n- Adoption reached 82%"
        document = parse_markdown(source)
        metric = next(block for block in document.blocks if block.type == "bullets")
        heading = next(block for block in document.blocks if block.type == "heading" and block.level == 2)
        cover = next(block for block in document.blocks if block.type == "heading" and block.level == 1)
        response = {
            "schema": "storyboard/v1",
            "slides": [
                {"kind": "cover", "title": "Report", "source_block_ids": [cover.id]},
                {
                    "kind": "content",
                    "title": "Adoption is established",
                    "source_block_ids": [heading.id, metric.id],
                    "archetype": "metrics_row",
                    "key_message": "Adoption reached 82%.",
                },
            ],
        }
        prompts = []

        def fake_llm(prompt: str) -> str:
            prompts.append(prompt)
            return __import__("json").dumps(response)

        report = run_pipeline(
            source,
            out_dir=tmp_path / "storyboard",
            llm_fn=fake_llm,
            task_spec={"audience": "executive team", "objective": "approve rollout"},
            gate_deck=False,
        )

        assert report["stages"]["plan"]["source"] == "storyboard"
        assert report["stages"]["plan"]["page_total"] == 2
        assert report["metadata"]["llm"] == "sampled"
        assert report["storyboard"]["slides"][1]["key_message"] == "Adoption reached 82%."
        assert len(prompts) == 1
        assert "executive team" in prompts[0]
        assert "approve rollout" in prompts[0]

    def test_pipeline_reports_nonvisual_model_fallback(self, tmp_path, monkeypatch):
        from ppt_agent.sdk import PptAgent

        def fake_gate(self, pptx, *, workspace, reference=None, policy=None,
                      critic=None, visual_review_reason=None):
            return {
                "passed": True,
                "mode": "rendered",
                "critic_gate": {
                    "passed": True,
                    "findings": [],
                    "mode": "deterministic_fallback",
                    "warning": visual_review_reason,
                },
            }

        monkeypatch.setattr(PptAgent, "gate", fake_gate)
        report = run_pipeline(
            SAMPLE,
            out_dir=tmp_path / "nonvisual",
            gate_deck=True,
            visual_review_reason="当前模型未声明视觉能力",
        )

        assert report["visual_review"]["status"] == "deterministic_fallback"
        assert report["visual_review"]["warning"] == "当前模型未声明视觉能力"

    def test_skipped_gate_does_not_claim_deterministic_review(self, tmp_path):
        report = run_pipeline(
            SAMPLE,
            out_dir=tmp_path / "skipped-gate",
            gate_deck=False,
        )

        assert report["visual_review"]["status"] == "not_run"
        assert "门禁已关闭" in report["visual_review"]["warning"]
        assert "将退回确定性检查" not in report["visual_review"]["warning"]
