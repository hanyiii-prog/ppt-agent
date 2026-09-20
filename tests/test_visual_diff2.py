"""Visual Diff 2.0 tests: status distinction, region diff, critical gate."""
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import ppt_agent.visual_regression as vr
from ppt_agent.visual_regression import (
    compare_page_regions,
    edge_diff,
    region_score,
    regions_from_fidelity,
    render_and_compare,
    visual_regression,
    visual_status,
)

from tests.fidelity_fixtures import build_rich_pptx, mutate_pptx
from ppt_agent.fidelity_model import build_deck_fidelity


def _make(path: Path, *, body_rect: bool = True, title_rect: bool = False, size=(320, 180)) -> None:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    if body_rect:
        draw.rectangle((40, 100, 180, 130), fill="navy")  # inside body band
    if title_rect:
        draw.rectangle((40, 18, 180, 34), fill="navy")    # inside title band
    image.save(path)


def test_identical_pages_pass_with_full_scores(tmp_path: Path):
    ref_dir = tmp_path / "ref"; cand_dir = tmp_path / "cand"
    ref_dir.mkdir(); cand_dir.mkdir()
    _make(ref_dir / "slide-1.png"); _make(cand_dir / "slide-1.png")
    report = visual_regression(ref_dir, cand_dir)
    assert report.passed
    assert report.status == "visual_pass"
    assert report.page_score == 1.0
    assert report.critical_region_score == 1.0
    assert report.critical_gate_passed
    assert report.pages[0].edge_diff == 0.0


def test_title_band_failure_fails_critical_gate_even_when_body_is_clean(tmp_path: Path):
    ref_dir = tmp_path / "ref"; cand_dir = tmp_path / "cand"
    ref_dir.mkdir(); cand_dir.mkdir()
    _make(ref_dir / "slide-1.png", title_rect=False)
    _make(cand_dir / "slide-1.png", title_rect=True)  # both keep the body rect
    report = visual_regression(ref_dir, cand_dir)
    assert report.status == "visual_fail"
    assert not report.critical_gate_passed
    by_region = {m.region: m for m in report.region_metrics}
    assert not by_region["title"].passed
    assert by_region["body"].passed, "body band must stay clean"
    assert report.critical_region_score < 1.0


def test_edge_diff_separates_identical_from_changed(tmp_path: Path):
    a = tmp_path / "a.png"; b = tmp_path / "b.png"
    _make(a)
    _make(b, body_rect=False, title_rect=True)
    gray_a = vr._to_gray_array(a)
    gray_b = vr._to_gray_array(b, (gray_a.shape[1], gray_a.shape[0]))
    assert edge_diff(gray_a, gray_a) == 0.0
    assert edge_diff(gray_a, gray_b) > 0.0


def test_region_score_bounds():
    assert region_score(0.0, 0.0, 1.0) == 1.0
    assert region_score(0.5, 0.5, 0.5) == 0.0


def test_renderer_unavailable_is_explicit_and_never_passes(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(vr, "preview_backend", lambda: None)
    pptx = build_rich_pptx(tmp_path / "a.pptx")
    status = visual_status(pptx, pptx, tmp_path / "work")
    assert status["status"] == "renderer_unavailable"
    assert status["passed"] is False


def test_renderer_error_is_explicit_and_never_passes(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(vr, "preview_backend", lambda: "libreoffice")
    monkeypatch.setattr(vr, "office_binary", lambda: "/does-not-exist/soffice")

    def boom(cmd):
        raise RuntimeError(f"command failed: {cmd}")

    monkeypatch.setattr(vr, "_run", boom)
    pptx = build_rich_pptx(tmp_path / "a.pptx")
    status = visual_status(pptx, pptx, tmp_path / "work")
    assert status["status"] == "renderer_error"
    assert status["passed"] is False


def test_real_pptx_render_and_compare_roundtrip(tmp_path: Path):
    reference = build_rich_pptx(tmp_path / "ref.pptx")
    same = visual_status(reference, reference, tmp_path / "same")
    assert same["status"] == "visual_pass"
    assert same["passed"] is True
    assert same["report"]["pages"][0]["mae"] == 0.0

    # a ~15px shift is above structural tolerance but inside whole-page visual
    # thresholds; the mutated page must still differ pixel-wise (mae > 0)
    candidate = mutate_pptx(reference, tmp_path / "cand.pptx", "geometry_changed")
    diff = visual_status(reference, candidate, tmp_path / "diff")
    assert diff["status"] in ("visual_pass", "visual_fail")
    page3 = diff["report"]["pages"][2]
    assert page3["mae"] > 0.0
    assert diff["passed"] == (diff["status"] == "visual_pass")


def test_render_and_compare_accepts_region_boxes(tmp_path: Path):
    reference = build_rich_pptx(tmp_path / "ref.pptx")
    report = render_and_compare(
        reference, reference, tmp_path / "work",
        regions={"logo": (0.0, 0.0, 0.2, 0.2)},
    )
    regions = {m.region for m in report.region_metrics}
    assert "logo" in regions
    assert report.critical_gate_passed


def test_regions_from_fidelity_maps_pictures_and_logos(tmp_path: Path):
    deck = build_deck_fidelity(build_rich_pptx(tmp_path / "rich.pptx"))
    slide = deck.slides[2]
    page_size = slide.page_size
    boxes = regions_from_fidelity(slide, page_size)
    assert "image" in boxes, "content slide carries a picture"
    x, y, w, h = boxes["image"]
    assert 0.0 <= x < 1.0 and 0.0 <= y < 1.0 and w > 0 and h > 0
    # default bands remain available
    assert "title" in boxes and "footer" in boxes


def test_region_metrics_cover_all_default_bands(tmp_path: Path):
    ref = tmp_path / "r.png"; cand = tmp_path / "c.png"
    _make(ref); _make(cand)
    metrics = compare_page_regions(ref, cand)
    names = {m.region for m in metrics}
    assert {"background", "header", "title", "body", "footer", "chrome"} <= names
    assert all(0.0 <= m.score <= 1.0 for m in metrics)
