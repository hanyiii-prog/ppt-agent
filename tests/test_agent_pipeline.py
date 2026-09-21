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
    assert report["schema"] == "pipeline/v2"
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
    presentation, _cache = plan_to_ir(plan, document, title="测试")
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


# ---- content-page integrity (blank control / duplicated heading fixes) ----

_PAIRING_SAMPLE = """# 项目汇报

## 建设背景

### (一)背景说明

1. 顶层指导方针

院领导明确指出，不追求一步到位的昂贵平台，以点带面跑通试点，先搭好基础数据架构。

2. 现状与核心矛盾

医院年病历量超百万份，诊疗信息以流水账形式散落在各业务系统中，历史数据长期沉睡。

3. 破局思路

用好现有信息化底座，立足既有系统，采用多源检索、精准入组的技术路线，实现敏捷破冰。
"""


def test_content_pages_pair_title_with_their_body():
    """A card title must never be paginated away from its body paragraph,
    which used to render as a title-only card with a blank body box."""
    from ppt_agent.agent.pipeline import _plan_to_clone_pages
    from ppt_agent.content_analyzer import analyze_content
    from ppt_agent.narrative_engine import build_narrative
    from ppt_agent.page_archetype import annotate_plan
    from ppt_agent.presentation_plan import build_presentation_plan

    document = parse_markdown(_PAIRING_SAMPLE, source="pairing.md")
    analyzed = analyze_content(document)
    build_narrative(analyzed)
    plan = build_presentation_plan(analyzed)
    annotated = annotate_plan(plan, analyzed)
    pages = _plan_to_clone_pages(annotated, document)

    content_pages = [p for p in pages if p.get("role") == "content"]
    assert content_pages, "sample must produce at least one content page"

    checked = 0
    for page in content_pages:
        for card in page.get("cards") or []:
            title = (card.get("title") or "").strip()
            lines = card.get("lines")
            body = card.get("body")
            if lines is not None:
                has_body = any((x or "").strip() for x in lines)
                first = (lines[0].strip() if lines else "")
            else:
                has_body = bool((body or "").strip())
                first = (body or "").strip()
            if not title:
                continue
            # 1) no blank control: a titled card carries real body text.
            assert has_body, f"title {title!r} rendered with an empty body"
            # 2) no duplicated heading: body is not a copy/prefix of the title.
            assert not first.startswith(title), (
                f"body duplicates title {title!r}: {first!r}"
            )
            checked += 1
    assert checked, "expected to inspect several paired cards"


def test_split_card_text_never_duplicates_or_blanks():
    from ppt_agent.agent.pipeline import _split_card_text

    # lead-in split
    t, b = _split_card_text("部署灵活：支持信创环境私有化部署")
    assert t and b and not b.startswith(t)
    # long clauseless prose -> disjoint title/body, no blank body
    long_text = "覆盖口腔恶性肿瘤从防筛诊疗到科研的完整闭环管理流程体系"
    t, b = _split_card_text(long_text)
    assert t and b and long_text.startswith(t)
    assert b and not b.startswith(t)
    # short title stays whole with no body
    t, b = _split_card_text("破局思路")
    assert t == "破局思路" and b == ""
