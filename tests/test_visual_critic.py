from pathlib import Path

from PIL import Image

from ppt_agent.visual_critic import HeuristicVisualCritic, review_pages


def test_critic_flags_nearly_blank_page(tmp_path: Path):
    page = tmp_path / "slide-1.png"
    Image.new("RGB", (320, 180), "white").save(page)
    report = review_pages([page], HeuristicVisualCritic())
    assert not report.passed
    assert report.pages[0].rule == "near_blank"


def test_critic_accepts_content_page(tmp_path: Path):
    page = tmp_path / "slide-1.png"
    image = Image.new("RGB", (320, 180), "white")
    for x in range(40, 180):
        for y in range(40, 130):
            image.putpixel((x, y), (20, 40, 80))
    image.save(page)
    report = review_pages([page], HeuristicVisualCritic())
    assert report.passed
