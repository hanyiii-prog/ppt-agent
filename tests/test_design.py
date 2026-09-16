from ppt_agent.design import (
    SlideDesigner,
    design_presentation,
    is_pre_designed,
    normalize_purpose,
    text_height,
    wrap_lines,
)
from ppt_agent.ir import Component, Presentation, Slide
from ppt_agent.theme import DEFAULT_THEME, resolve_theme


def _slide(purpose: str, title: str, *points: str) -> Slide:
    components = [Component(type="title", id="t", text=title)]
    components += [Component(type="text", id=f"p{i}", text=point) for i, point in enumerate(points)]
    return Slide(id="s1", purpose=purpose, claim=title, components=components)


def _deck(*slides: Slide) -> Presentation:
    return Presentation(version="0.1", title="Deck", slides=list(slides))


def test_normalize_purpose_handles_chinese_and_english():
    assert normalize_purpose("cover") == "cover"
    assert normalize_purpose("封面") == "cover"
    assert normalize_purpose("目录") == "agenda"
    assert normalize_purpose("总结") == "closing"
    assert normalize_purpose("章节") == "section"
    assert normalize_purpose("项目背景与建设目标") == "content"
    assert normalize_purpose(None) == "content"


def test_wrap_lines_measures_cjk_and_latin_on_one_metric():
    lines = wrap_lines("这是一段需要换行的中文文本内容", 2.0, 16.0)
    assert len(lines) >= 2
    assert "".join(lines) == "这是一段需要换行的中文文本内容"
    # Latin glyphs are narrower, so more of them fit in the same width.
    assert len(wrap_lines("abcdefghij", 1.0, 20.0)[0]) >= 3


def test_text_height_grows_with_line_count():
    short = text_height("短", 6.0, 16.0)
    tall = text_height("这是一段足够长的文本，在较窄的宽度下必然折行显示", 1.5, 16.0)
    assert tall > short


def test_cover_uses_paragraph_as_headline_when_heading_is_a_marker():
    designer = SlideDesigner(DEFAULT_THEME)
    slide = designer.design(_slide("封面", "封面", "真正的标题", "2026 年度"), index=1, total=2, deck_title="Deck")
    texts = {component.id: component.text for component in slide.components}
    assert texts["cover-title"] == "真正的标题"
    assert texts["cover-sub"] == "2026 年度"


def test_cover_falls_back_to_deck_title():
    designer = SlideDesigner(DEFAULT_THEME)
    slide = designer.design(_slide("封面", "封面"), index=1, total=1, deck_title="季报")
    texts = {component.id: component.text for component in slide.components}
    assert texts["cover-title"] == "季报"


def test_content_layout_decorates_and_stays_inside_the_canvas():
    designer = SlideDesigner(DEFAULT_THEME)
    slide = designer.design(
        _slide("content", "章节标题", "第一个要点", "第二个要点", "第三个要点"),
        index=3, total=8, deck_title="Deck",
    )
    by_id = {component.id: component for component in slide.components}
    assert "head-anchor" in by_id and "head-rule" in by_id
    assert by_id["footer-page"].text == "03 / 08"
    assert all(
        component.x is not None and component.y is not None
        and component.x + (component.w or 0) <= 13.34
        and component.y + (component.h or 0) <= 7.51
        for component in slide.components
    )


def test_agenda_numbers_every_row():
    designer = SlideDesigner(DEFAULT_THEME)
    slide = designer.design(_slide("目录", "目录", "甲", "乙", "丙"), index=2, total=5, deck_title="Deck")
    numbers = [c.text for c in slide.components if (c.id or "").endswith("-no")]
    assert numbers == ["01", "02", "03"]


def test_closing_paints_a_full_bleed_inverse_background():
    designer = SlideDesigner(DEFAULT_THEME)
    slide = designer.design(_slide("总结", "总结", "结论一"), index=8, total=8, deck_title="Deck")
    background = slide.data["background"]["fill"]["rgb"]
    assert background == DEFAULT_THEME.primary_deep
    assert any(component.id == "closing-bg" for component in slide.components)


def test_pre_designed_slides_are_not_recomposed():
    pinned = Slide(
        id="pinned",
        purpose="content",
        components=[Component(type="text", text="kept", x=1.0, y=1.0, w=2.0, h=1.0)],
    )
    assert is_pre_designed(pinned)

    designed = design_presentation(_deck(pinned), theme=None)
    assert designed.slides[0] is pinned


def test_design_presentation_assigns_page_numbers_across_the_deck():
    deck = _deck(
        _slide("封面", "封面", "标题"),
        _slide("content", "甲", "要点"),
        _slide("总结", "总结", "结论"),
    )
    designed = design_presentation(deck, theme=None)
    page = [c for c in designed.slides[1].components if c.id == "footer-page"]
    assert page and page[0].text == "02 / 03"


def test_theme_overrides_are_applied_from_the_presentation():
    deck = _deck(_slide("content", "标题", "要点"))
    deck.theme = {"name": "graphite", "slide_title_pt": 30.0, "accent": "FF0000"}
    designed = design_presentation(deck, theme=None)
    title = [c for c in designed.slides[0].components if c.id == "head-title"][0]
    assert title.style["font"]["size_pt"] == 30.0
    assert title.style["font"]["rgb"] == "1C252C"
    anchor = [c for c in designed.slides[0].components if c.id == "head-anchor"][0]
    assert anchor.style["fill"]["rgb"] == "FF0000"


def test_resolve_theme_falls_back_to_default():
    assert resolve_theme("nope").name == DEFAULT_THEME.name
    assert resolve_theme("graphite").name == "graphite"
