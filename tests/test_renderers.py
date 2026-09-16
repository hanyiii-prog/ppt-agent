from pathlib import Path

import pytest

from ppt_agent.ir import Presentation
from ppt_agent.renderers import (
    DEFAULT_PREFERENCE,
    HtmlRenderer,
    NativePptxRenderer,
    RenderError,
    RenderRequest,
    describe_renderers,
    get_renderer,
    preference,
    register_renderer,
    registered_names,
    render_html_deck,
    render_with,
    select_renderer,
    set_preference,
    unregister_renderer,
)

FIXTURE = {
    "version": "1.0",
    "metadata": {"title": "Renderer SDK"},
    "theme": {"slide_size_inches": {"width": 13.333, "height": 7.5}},
    "slides": [
        {
            "id": "slide-01",
            "purpose": "cover",
            "components": [{"type": "title", "text": "封面标题"}],
        },
        {
            "id": "slide-02",
            "purpose": "content",
            "components": [
                {"type": "text", "text": "绝对定位", "x": 1.0, "y": 1.0, "w": 5.0, "h": 1.0,
                 "style": {"fill": {"rgb": "EEEEEE", "alpha": 0.5},
                           "font": {"size_pt": 24, "bold": True, "rgb": "112233", "alignment": "center"}}},
                {"type": "paragraph", "text": "流式段落"},
                {"type": "shape", "x": 8.0, "y": 1.0, "w": 2.0, "h": 1.5,
                 "style": {"fill": {"rgb": "336699"}, "line": {"rgb": "000000", "width_pt": 2}}},
                {"type": "chart", "x": 1.0, "y": 4.0, "w": 4.0, "h": 2.0, "data": {"name": "月度趋势"}},
                {"type": "table", "x": 6.0, "y": 4.0, "w": 5.0, "h": 2.0,
                 "data": {"rows": [["指标", "数值"], ["覆盖率", "100%"]]}},
            ],
        },
        {
            "id": "slide-03",
            "purpose": "closing",
            "speaker_notes": "结束页备注",
            "components": [{"type": "title", "text": "总结"}],
        },
    ],
}


@pytest.fixture()
def presentation() -> Presentation:
    return Presentation.from_dict(FIXTURE)


def test_builtin_renderers_are_registered():
    assert registered_names() == ["html", "native-pptx"]
    assert preference() == DEFAULT_PREFERENCE
    # The inventory is listed in selection order, not alphabetically.
    assert [item["name"] for item in describe_renderers()] == ["native-pptx", "html"]


def test_automatic_selection_prefers_the_editable_engine():
    pytest.importorskip("pptx")
    assert select_renderer().name == "native-pptx"
    assert select_renderer(editable=True).name == "native-pptx"
    assert select_renderer(editable=False).name == "html"


def test_selection_falls_back_to_html_without_python_pptx(monkeypatch):
    monkeypatch.setattr(NativePptxRenderer, "available", lambda self: False)
    assert select_renderer().name == "html"
    with pytest.raises(RenderError):
        select_renderer("native-pptx")
    with pytest.raises(RenderError):
        select_renderer(editable=True)


def test_unknown_renderer_raises():
    with pytest.raises(RenderError) as exc:
        get_renderer("docx")
    assert "unknown renderer" in str(exc.value)


def test_registering_a_duplicate_requires_an_explicit_override():
    existing = get_renderer("html")
    with pytest.raises(RenderError):
        register_renderer(HtmlRenderer())
    try:
        register_renderer(HtmlRenderer(), override=True)
        assert get_renderer("html") is not None
    finally:
        register_renderer(existing, override=True)


def test_preference_can_be_reordered_and_reset():
    original = preference()
    try:
        assert set_preference(["html", "native-pptx"]) == ("html", "native-pptx")
        assert select_renderer().name == "html"
        assert set_preference(["html", "does-not-exist"]) == ("html",)
    finally:
        set_preference(original)
    assert preference() == DEFAULT_PREFERENCE


def test_render_request_and_result_are_serialisable(tmp_path: Path):
    request = RenderRequest(output=Path("deck.pptx"), iteration=2, repair_requests=({"page": 1},))
    assert request.output == Path("deck.pptx")
    result = HtmlRenderer().render(
        Presentation.from_dict(FIXTURE), RenderRequest(output=tmp_path / "deck.html")
    )
    payload = result.to_dict()
    assert payload["renderer"] == "html" and payload["slide_count"] == 3
    assert payload["editable"] is False and payload["media_type"] == "text/html"


def test_native_renderer_emits_an_editable_deck(presentation, tmp_path: Path):
    pytest.importorskip("pptx")
    result = render_with(presentation, tmp_path / "deck.pptx")
    assert result.renderer == "native-pptx"
    assert result.editable is True
    assert Path(result.path).exists()
    assert result.slide_count == 3
    assert result.metrics["bytes"] > 0


def test_native_renderer_build_callback_closes_the_repair_loop(presentation, tmp_path: Path, monkeypatch):
    from ppt_agent.delivery import DeliveryPolicy, run_repair_loop

    pytest.importorskip("pptx")
    renderer = get_renderer("native-pptx")
    build = renderer.build_callback(presentation, tmp_path / "loop.pptx")
    assert isinstance(build(1, []), Path)

    calls: list[int] = []

    def spy(iteration, repair_requests):
        calls.append(iteration)
        return build(iteration, repair_requests)

    def fake_validate(pptx, workspace, **kwargs):
        from ppt_agent.page_validation import DeckGateReport, PageGate
        from ppt_agent.visual_critic import CriticReport

        passed = len(calls) >= 2
        page = PageGate(1, 1, 0, 0, 320, 180, 0.0, passed, [] if passed else ["synthetic"])
        return DeckGateReport(passed, 1, [page]), CriticReport(True), None

    monkeypatch.setattr("ppt_agent.delivery.validate_delivery", fake_validate)
    report = run_repair_loop(spy, workspace=tmp_path / "loop", policy=DeliveryPolicy(max_repair_iterations=3))
    assert report.passed and report.iterations == 2


def test_html_renderer_is_deterministic(presentation, tmp_path: Path):
    first, _ = render_html_deck(presentation, tmp_path / "a.html")
    second, _ = render_html_deck(presentation, tmp_path / "b.html")
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


def test_html_renderer_produces_a_printable_self_contained_deck(presentation, tmp_path: Path):
    path, warnings = render_html_deck(presentation, tmp_path / "deck.html")
    text = path.read_text(encoding="utf-8")
    assert warnings == []
    assert text.count('class="slide"') == 3
    assert "<!DOCTYPE html>" in text
    assert "@media print" in text
    assert "--slide-w:1280px" in text and "--slide-h:720px" in text
    assert "封面标题" in text
    assert "结束页备注" in text          # speaker notes are preserved
    assert 'class="comp table"' in text and "覆盖率" in text
    assert "[chart] 月度趋势" in text
    assert "rgba(238,238,238,0.5000)" in text   # alpha from IR style is honoured


def test_html_renderer_escapes_untrusted_text(tmp_path: Path):
    payload = {
        "version": "1.0",
        "metadata": {"title": "<script>alert(1)</script>"},
        "slides": [{
            "id": "s1",
            "purpose": "content",
            "components": [{"type": "text", "text": '<img src=x onerror="alert(1)">'}],
        }],
    }
    path, _ = render_html_deck(Presentation.from_dict(payload), tmp_path / "escaped.html")
    text = path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "<img src=x onerror=" not in text
    assert "&lt;img src=x onerror=" in text


def test_html_renderer_warns_about_unresolvable_assets(tmp_path: Path):
    payload = {
        "version": "1.0",
        "metadata": {"title": "Assets"},
        "slides": [{
            "id": "s1", "purpose": "content",
            "components": [{"type": "image", "x": 1.0, "y": 1.0, "w": 3.0, "h": 2.0,
                            "data": {"path": str(tmp_path / "missing.png")}}],
        }],
    }
    path, warnings = render_html_deck(Presentation.from_dict(payload), tmp_path / "assets.html")
    assert any("image not found" in warning for warning in warnings)
    assert "[image]" in path.read_text(encoding="utf-8")


def test_html_renderer_inlines_image_bytes(tmp_path: Path):
    payload = {
        "version": "1.0",
        "metadata": {"title": "Inline"},
        "slides": [{
            "id": "s1", "purpose": "content",
            "components": [{"type": "image", "x": 1.0, "y": 1.0, "w": 2.0, "h": 1.0,
                            "data": {"bytes": b"\x89PNG\r\n\x1a\n", "media_type": "image/png"}}],
        }],
    }
    path, warnings = render_html_deck(Presentation.from_dict(payload), tmp_path / "inline.html")
    assert warnings == []
    assert "data:image/png;base64," in path.read_text(encoding="utf-8")


def test_render_html_deck_rejects_a_non_presentation(tmp_path: Path):
    with pytest.raises(RenderError):
        HtmlRenderer().render({"not": "ir"}, RenderRequest(output=tmp_path / "x.html"))


def test_unregistering_a_renderer_removes_it():
    extra = HtmlRenderer()
    extra.name = "temporary"
    extra.display_name = "Temporary"
    register_renderer(extra)
    assert "temporary" in registered_names()
    unregister_renderer("temporary")
    assert "temporary" not in registered_names()
