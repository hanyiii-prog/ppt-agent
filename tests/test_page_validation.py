from pathlib import Path

from pptx import Presentation

from ppt_agent.page_validation import infer_page_role, validate_rendered_pages
from PIL import Image


def test_page_roles_first_last_and_chapter():
    assert infer_page_role(1, 4, "封面") == "first"
    assert infer_page_role(2, 4, "目录") == "chapter"
    assert infer_page_role(3, 4, "正文") == "body"
    assert infer_page_role(4, 4, "结论") == "last"


def test_gate_records_text_and_image_shape_counts(tmp_path: Path):
    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[6])
    slide = prs.slides[0]
    box = slide.shapes.add_textbox(0, 0, 1000000, 500000)
    box.text = "标题"
    pptx_path = tmp_path / "deck.pptx"
    prs.save(pptx_path)

    image = tmp_path / "slide-1.png"
    Image.new("RGB", (320, 180), "white").save(image)
    report = validate_rendered_pages(pptx_path, [image])
    assert report.pages[0].role == "first"
    assert report.pages[0].text_shapes == 1
    assert report.pages[0].image_shapes == 0
