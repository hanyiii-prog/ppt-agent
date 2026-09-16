import json
from pathlib import Path

import pytest

from ppt_agent import PptAgent
from ppt_agent.adapters import GenericAdapter
from ppt_agent.contracts import IR_SCHEMA_VERSION

# The shared sample markdown has an H1 title plus four H2 sections.
SAMPLE_SLIDES = 4


def test_capabilities_payload_is_complete():
    payload = PptAgent().capabilities()
    assert payload["core_api_version"] == "1.0"
    assert payload["ir_schema_version"] == IR_SCHEMA_VERSION
    assert payload["adapter"]["name"] == "local"
    assert payload["negotiation"]["ok"] is True
    assert {renderer["name"] for renderer in payload["renderers"]} == {"html", "native-pptx"}
    assert payload["host_profiles"]
    json.dumps(payload, ensure_ascii=False)


def test_plan_turns_markdown_into_stamped_ir(sample_markdown):
    presentation = PptAgent().plan(
        sample_markdown, title="上线总结", audience="院方", objective="汇报"
    )
    assert presentation.version == IR_SCHEMA_VERSION
    assert len(presentation.slides) == SAMPLE_SLIDES
    assert presentation.title == "上线总结"
    assert presentation.audience == "院方"
    assert presentation.objective == "汇报"
    assert presentation.to_dict()["ir_version"] == IR_SCHEMA_VERSION


def test_parse_uses_the_flat_markdown_mapper(sample_markdown):
    presentation = PptAgent().parse(sample_markdown, source_id="deck.md")
    assert presentation.sources[0]["id"] == "deck.md"
    assert presentation.slides[0].purpose == "封面"


def test_ir_round_trips_through_disk(sample_markdown, workspace: Path):
    agent = PptAgent()
    presentation = agent.plan(sample_markdown)
    path = agent.save_ir(presentation, workspace / "ir" / "deck.json")
    assert json.loads(path.read_text(encoding="utf-8"))["ir_version"] == IR_SCHEMA_VERSION
    reloaded = agent.load_ir(path)
    assert reloaded.title == presentation.title
    assert len(reloaded.slides) == len(presentation.slides)


def test_validate_ir_accepts_a_presentation_object(sample_markdown):
    agent = PptAgent()
    assert agent.validate_ir(agent.plan(sample_markdown))["passed"] is True
    assert agent.validate_ir({"version": "1.0", "metadata": {}, "slides": []})["passed"] is True
    assert agent.validate_ir({"version": "9.9", "metadata": {}, "slides": []})["passed"] is False


def test_renderer_for_reports_the_selected_engine():
    pytest.importorskip("pptx")
    assert PptAgent().renderer_for() == "native-pptx"
    assert PptAgent().renderer_for(editable=False) == "html"


def test_build_produces_every_artifact_and_a_manifest(sample_markdown, workspace: Path):
    pytest.importorskip("pptx")
    outcome = PptAgent().build(markdown=sample_markdown, out_dir=workspace, stem="deck")
    assert outcome.ok is True
    assert outcome.slide_count == SAMPLE_SLIDES
    assert outcome.renderer == "native-pptx"
    for path in (outcome.ir_path, outcome.pptx_path, outcome.html_path):
        assert Path(path).exists(), path
    assert outcome.gate["passed"] is True
    assert outcome.gate["mode"] in {"rendered", "structural"}
    assert len(outcome.manifest["pages"]) == SAMPLE_SLIDES
    assert outcome.manifest["schema_version"] == "1.0"
    assert outcome.manifest["gate_mode"] == outcome.gate["mode"]
    assert json.loads(json.dumps(outcome.to_dict(), ensure_ascii=False))["slide_count"] == SAMPLE_SLIDES


def test_build_writes_a_html_preview_that_matches_the_deck(sample_markdown, workspace: Path):
    pytest.importorskip("pptx")
    outcome = PptAgent().build(markdown=sample_markdown, out_dir=workspace)
    html_text = Path(outcome.html_path).read_text(encoding="utf-8")
    assert html_text.count('class="slide"') == SAMPLE_SLIDES


def test_build_can_disable_gates_and_html(sample_markdown, workspace: Path):
    pytest.importorskip("pptx")
    outcome = PptAgent().build(markdown=sample_markdown, out_dir=workspace, gate=False, emit_html=False)
    assert outcome.gate is None and outcome.manifest is None and outcome.html_path is None
    assert Path(outcome.pptx_path).exists()


def test_build_from_an_existing_ir(sample_markdown, workspace: Path):
    pytest.importorskip("pptx")
    agent = PptAgent()
    presentation = agent.plan(sample_markdown)
    outcome = agent.build(presentation=presentation, out_dir=workspace, emit_html=False)
    assert outcome.ok and outcome.slide_count == SAMPLE_SLIDES


def test_build_requires_some_input(workspace: Path):
    with pytest.raises(ValueError):
        PptAgent().build(out_dir=workspace)


def test_fact_lock_passes_when_every_claim_is_registered(sample_markdown, workspace: Path):
    pytest.importorskip("pptx")
    agent = PptAgent()
    presentation = agent.plan(sample_markdown)
    facts = [
        {"claim": component.text, "source_id": "source.md", "locator": slide.id}
        for slide in presentation.slides
        for component in slide.components
        if component.text
    ]
    assert facts
    outcome = agent.build(presentation=presentation, out_dir=workspace, facts=facts, emit_html=False)
    assert outcome.fact_audit["unsupported"] == 0
    assert outcome.fact_audit["passed"] is True
    assert outcome.ok is True


def test_fact_lock_blocks_on_an_unsupported_claim(sample_markdown, workspace: Path):
    agent = PptAgent()
    presentation = agent.plan(sample_markdown)
    outcome = agent.build(
        presentation=presentation,
        out_dir=workspace,
        facts=[{"claim": "完全不存在的说法", "source_id": "nowhere"}],
        emit_html=False,
    )
    assert outcome.fact_audit["passed"] is False
    assert outcome.fact_audit["unsupported"] > 0
    assert outcome.ok is False


def test_gate_degrades_to_structural_checks_without_a_rasteriser(sample_markdown, workspace: Path, monkeypatch):
    pytest.importorskip("pptx")
    monkeypatch.setattr("ppt_agent.visual_regression.rasteriser_available", lambda: False)
    agent = PptAgent()
    deck = agent.build(
        presentation=agent.plan(sample_markdown), out_dir=workspace, emit_html=False
    ).pptx_path
    report = agent.gate(deck, workspace=workspace / "qa")
    assert report["mode"] == "structural"
    assert report["degraded"] == ["render_preview"]
    assert report["page_gate"]["mode"] == "structural"
    assert report["critic_gate"] is None and report["visual_gate"] is None
    assert report["passed"] is True
    assert report["candidate"] == deck


def test_gate_uses_the_rendered_pipeline_when_a_rasteriser_exists(workspace: Path, monkeypatch):
    pptx = pytest.importorskip("pptx")
    prs = pptx.Presentation()
    prs.slides.add_slide(prs.slide_layouts[6])
    deck = workspace / "tiny.pptx"
    prs.save(str(deck))

    from ppt_agent import delivery
    from ppt_agent.visual_critic import CriticReport

    monkeypatch.setattr("ppt_agent.visual_regression.rasteriser_available", lambda: True)
    monkeypatch.setattr(delivery, "render_pptx", lambda path, out, **kwargs: [_fake_png(out)])
    monkeypatch.setattr(delivery, "review_pages", lambda pages, critic=None: CriticReport(True))

    report = PptAgent().gate(deck, workspace=workspace / "qa")
    assert report["mode"] == "rendered"
    assert report["degraded"] == []
    assert report["critic_gate"] == {"passed": True, "findings": []}
    assert report["visual_gate"] is None
    assert report["passed"] is True


def _fake_png(directory: Path) -> Path:
    from PIL import Image

    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    page = target / "slide-1.png"
    Image.new("RGB", (160, 90), (10, 10, 10)).save(page)
    return page


def test_generic_adapter_reports_the_degraded_gates():
    payload = PptAgent(GenericAdapter()).capabilities()
    assert payload["negotiation"]["missing"] == ["render_preview"]
    assert payload["negotiation"]["fallbacks"] == ["structural_gate_only"]
    assert payload["adapter"]["declared"] == ["filesystem"]
