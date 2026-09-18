"""Batch 3.D layout engine tests + the red-line-1 guard tests.

The guard: ``resolve_layout(..., engine="legacy")`` is byte-identical to the
pre-V2.1 algorithm, and absolute (template-injected) geometry is identical
between both engines -- the solver never touches template decisions.
"""

from __future__ import annotations

import pytest

from ppt_agent.ir import Component, Slide
from ppt_agent.layout import (
    check_constraints,
    fit_image,
    measure_text_block,
    page_weight,
    shrink_to_fit,
    solve,
    whitespace_ratio,
)
from ppt_agent.styling import MARGIN_IN, resolve_layout

W, H = 13.333, 7.5


def _slide(*components: Component, purpose: str = "content") -> Slide:
    return Slide(id="s1", purpose=purpose, components=list(components))


def _text(text: str, **style) -> Component:
    return Component(type="body", text=text, style={"font": style} if style else {})


def _boxes(slide: Slide, engine: str = "legacy"):
    return [(box.x, box.y, box.w, box.h, box.font_pt, box.absolute)
            for box in resolve_layout(slide, W, H, engine=engine)]


# --- red line 1 guards -------------------------------------------------------
def test_legacy_engine_is_byte_identical() -> None:
    """Golden values computed from the pre-V2.1 algorithm, pinned forever."""
    slide = _slide(
        _text("第一段要点文字"),
        _text("第二段要点文字"),
        purpose="content",
    )
    boxes = resolve_layout(slide, W, H)  # default engine must be legacy
    # golden: 7 CJK chars @20pt = 1 line -> h = 20/72*1.35 + 0.12 = 0.495
    assert [(b.x, b.y, b.w, b.h, b.font_pt, b.absolute) for b in boxes] == [
        (MARGIN_IN, 0.6, W - 2 * MARGIN_IN, 0.495, 20.0, False),
        (MARGIN_IN, 1.255, W - 2 * MARGIN_IN, 0.495, 20.0, False),
    ]


def test_absolute_geometry_identical_between_engines() -> None:
    """Template-injected boxes pass verbatim through BOTH engines."""
    absolute = Component(type="shape", x=1.234, y=2.345, w=3.456, h=4.567)
    slide = _slide(absolute, _text("正文"), purpose="content")
    legacy = _boxes(slide, "legacy")
    solver = _boxes(slide, "solver")
    assert solver[0] == legacy[0], "absolute box must be byte-identical"
    assert solver[0][5] is True


def test_engine_keyword_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        resolve_layout(_slide(_text("x")), W, H, engine="turbo")


# --- typography engine -------------------------------------------------------
def test_cjk_text_measures_wider_than_ascii() -> None:
    cjk = measure_text_block("汉字" * 20, 5.0, 20.0)
    ascii_text = measure_text_block("ab" * 20, 5.0, 20.0)
    assert cjk > ascii_text, "full-width CJK glyphs consume more width"


def test_shrink_to_fit_bounds() -> None:
    assert shrink_to_fit(20.0, 1.0, 2.0) == 20.0          # already fits
    assert shrink_to_fit(20.0, 4.0, 2.0) == 12.0          # factor 0.5, floored at min 12
    assert shrink_to_fit(8.0, 4.0, 2.0) == 12.0           # never below min 12


# --- image engine ------------------------------------------------------------
def test_fit_image_contain_and_center() -> None:
    fitted = fit_image(2000, 1000, 4.0, 4.0)
    assert fitted["mode"] == "contain"
    assert fitted["w"] == pytest.approx(4.0) and fitted["h"] == pytest.approx(2.0)
    assert fitted["offset_y"] == pytest.approx(1.0) and fitted["offset_x"] == 0.0


def test_fit_image_degenerate_input_falls_back() -> None:
    fitted = fit_image(0, 0, 4.0, 3.0)
    assert fitted["mode"] == "stretch" and fitted["w"] == 4.0


# --- constraint engine -------------------------------------------------------
def test_constraint_checker_finds_overlap_and_gap() -> None:
    boxes = [
        {"x": 0.7, "y": 0.6, "w": 5.0, "h": 1.0, "absolute": False},
        {"x": 0.7, "y": 1.2, "w": 5.0, "h": 1.0, "absolute": False},  # overlaps + tight gap
        {"x": 12.0, "y": 6.0, "w": 2.0, "h": 2.0, "absolute": False},  # out of bounds + margin
    ]
    kinds = {violation["kind"] for violation in check_constraints(boxes, W, H)}
    assert {"overlap", "min_gap", "out_of_bounds", "margin_breach"} <= kinds


def test_constraint_checker_clean_page() -> None:
    boxes = [
        {"x": 0.7, "y": 0.7, "w": 5.0, "h": 1.0, "absolute": False},
        {"x": 0.7, "y": 2.0, "w": 5.0, "h": 1.0, "absolute": False},
    ]
    assert check_constraints(boxes, W, H) == []


# --- whitespace / visual weight ----------------------------------------------
def test_whitespace_ratio_bounds() -> None:
    assert whitespace_ratio([], W, H) == 1.0
    full = [{"x": 0, "y": 0, "w": W, "h": H, "absolute": False}]
    assert whitespace_ratio(full, W, H) == pytest.approx(0.0, abs=0.01)


def test_page_weight_flags_top_heavy() -> None:
    top_only = [{"x": 0.7, "y": 0.7, "w": 10.0, "h": 2.0, "absolute": False}]
    weight = page_weight(top_only, W, H)
    assert weight["top_heavy"] is True
    assert weight["top_share"] == pytest.approx(1.0)


# --- solver behaviour --------------------------------------------------------
def test_solver_pushes_down_colliding_flow_boxes() -> None:
    slide = _slide(_text("第一段" * 30), _text("第二段" * 30), purpose="content")
    boxes = resolve_layout(slide, W, H, engine="solver")
    report: dict = {}
    boxes2 = resolve_layout(slide, W, H, engine="solver", report=report)
    assert boxes == boxes2, "solver must be deterministic"
    assert report["engine"] == "solver"
    bottoms = [box.y + box.h for box in boxes]
    assert bottoms[1] >= bottoms[0], "second flow box must sit below the first"


def test_solver_shrinks_on_overflow_and_reports() -> None:
    slide = _slide(
        _text("很长的正文内容，" * 60),
        _text("第二段很长的正文内容，" * 60),
        _text("第三段很长的正文内容，" * 60),
        purpose="content",
    )
    report: dict = {}
    boxes = resolve_layout(slide, W, H, engine="solver", report=report)
    assert all(box.y + box.h <= H + 0.01 for box in boxes), "no box may leave the slide"
    assert report["shrunk_elements"] or report["violations_after"], (
        "overflow is either fixed (shrunk) or honestly reported"
    )


def test_solver_grid_snaps_flow_y() -> None:
    slide = _slide(_text("要点一"), _text("要点二"), _text("要点三"), purpose="content")
    boxes = resolve_layout(slide, W, H, engine="solver")
    for box in boxes:
        if not box.absolute:
            assert abs(box.y / 0.05 - round(box.y / 0.05)) < 1e-6, f"y={box.y} off-grid"
