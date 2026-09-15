from pathlib import Path

from PIL import Image, ImageDraw

from ppt_agent.visual_regression import compare_images, visual_regression


def _make(path: Path, offset: int = 0) -> None:
    image = Image.new("RGB", (320, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40 + offset, 40, 180 + offset, 130), fill="navy")
    image.save(path)


def test_identical_page_passes(tmp_path: Path):
    ref = tmp_path / "ref.png"; cand = tmp_path / "cand.png"
    _make(ref); _make(cand)
    mae, mismatch, ssim, passed = compare_images(ref, cand)
    assert passed and mae == 0 and mismatch == 0 and ssim == 1


def test_changed_page_fails(tmp_path: Path):
    ref = tmp_path / "ref.png"; cand = tmp_path / "cand.png"
    _make(ref); _make(cand, offset=25)
    *_, passed = compare_images(ref, cand)
    assert not passed


def test_visual_regression_requires_every_page(tmp_path: Path):
    ref_dir = tmp_path / "ref"; cand_dir = tmp_path / "cand"
    ref_dir.mkdir(); cand_dir.mkdir()
    for i in (1, 2):
        _make(ref_dir / f"slide-{i}.png")
    _make(cand_dir / "slide-1.png")
    report = visual_regression(ref_dir, cand_dir)
    assert not report.passed
    assert report.page_count_reference == 2
    assert report.page_count_candidate == 1
