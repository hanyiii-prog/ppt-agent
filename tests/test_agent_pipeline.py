"""End-to-end pipeline tests (batch 3.F): every layer, one honest report."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pptx")

from ppt_agent.agent import plan_to_ir, run_pipeline
from ppt_agent.parsers import parse_markdown
from ppt_agent.presentation_plan import build_presentation_plan

SAMPLE = """# 口腔医院互联互通项目上线总结

## 项目概况

- 覆盖 5 个院区，服务 92 人团队
- 互联互通四甲评审通过

## 建设过程

- 完成数据治理与清洗
- 完成接口联调与压力测试
- 完成全院培训与演练

## 项目成效

- 数据抽取成功率 99.2%
- 上线按期率 100%

## 下阶段重点

- 推进专病数据库建设，首批聚焦种植科与口腔癌
"""


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> dict:
    out = tmp_path_factory.mktemp("pipeline") / "dist"
    return run_pipeline(SAMPLE, out_dir=out)


def test_pipeline_delivers_real_artifacts(report: dict) -> None:
    assert report["schema"] == "pipeline/v1"
    assert Path(report["artifacts"]["pptx"]).exists(), "native pptx must exist"
    assert Path(report["artifacts"]["html"]).exists(), "html preview must exist"
    assert report["page_total"] >= 6  # cover + toc + 4 sections(+content)


def test_pipeline_report_discloses_llm_off(report: dict) -> None:
    assert report["metadata"]["llm"] == "off"
    assert report["stages"]["narrative"]["mode"] == "rules"


def test_pipeline_stages_are_all_present(report: dict) -> None:
    stages = report["stages"]
    for key in ("parse", "analyze", "narrative", "plan", "archetypes",
                "fidelity", "repair"):
        assert key in stages, f"stage {key} missing from report"
    assert stages["fidelity"]["mode"] == "designed"
    assert report["gates"]["fidelity_report"]["gates"]
    assert report["gates"]["delivery"]["passed"] is True


def test_pipeline_archetypes_cover_content_pages(report: dict) -> None:
    archetypes = report["stages"]["archetypes"]
    assert archetypes and all(value for value in archetypes.values())


def test_plan_to_ir_components_carry_absolute_geometry(tmp_path: Path) -> None:
    document = parse_markdown(SAMPLE)
    plan = build_presentation_plan(document)
    presentation = plan_to_ir(plan, document, title="测试")
    assert presentation.title == "测试"
    for slide in presentation.slides:
        assert slide.components, f"{slide.id} has no components"
        for component in slide.components:
            for key in ("x", "y", "w", "h"):
                assert isinstance(getattr(component, key), float), (
                    f"{slide.id}/{component.type} missing absolute {key}"
                )
            assert 0 <= component.x <= 13.333 and 0 <= component.y <= 7.5
            assert component.x + component.w <= 13.34 and component.y + component.h <= 7.51


def test_plan_to_ir_refuses_template_dna_honestly(tmp_path: Path) -> None:
    document = parse_markdown(SAMPLE)
    plan = build_presentation_plan(document)
    with pytest.raises(ValueError, match="clone route"):
        plan_to_ir(plan, document, template_dna={"schema": "template-dna/v0.4",
                                                 "slides": [{"slide": 1}]})


def test_pipeline_llm_sampled_end_to_end(tmp_path: Path) -> None:
    def fake_llm(prompt: str) -> str:
        return "\n".join(line for line in prompt.splitlines() if line.startswith("- "))

    report = run_pipeline(SAMPLE, out_dir=tmp_path / "dist-llm", llm_fn=fake_llm)
    assert report["metadata"]["llm"] == "sampled"
