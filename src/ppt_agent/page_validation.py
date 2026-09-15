from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE


@dataclass
class PageGate:
    page: int
    shape_count: int
    out_of_bounds: int
    zero_size: int
    rendered_width: int
    rendered_height: int
    blank_ratio: float
    passed: bool
    issues: list[str]
    role: str = "unknown"
    text_shapes: int = 0
    image_shapes: int = 0


@dataclass
class DeckGateReport:
    passed: bool
    slide_count: int
    pages: list[PageGate]

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "slide_count": self.slide_count,
            "pages": [asdict(p) for p in self.pages],
        }


def infer_page_role(index: int, slide_count: int, title_text: str = "") -> str:
    """Classify page role without assuming a particular deck's business semantics."""
    if slide_count <= 0:
        return "unknown"
    if index == 1:
        return "first"
    if index == slide_count:
        return "last"
    normalized = title_text.strip().lower()
    chapter_markers = ("目录", "contents", "chapter", "章节", "概述", "overview")
    if normalized and any(marker in normalized for marker in chapter_markers):
        return "chapter"
    return "body"


def _shape_stats(slide):
    text_shapes = image_shapes = 0
    for shape in slide.shapes:
        if getattr(shape, "has_text_frame", False):
            text_shapes += 1
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            image_shapes += 1
    return text_shapes, image_shapes


def _title_text(slide) -> str:
    for shape in slide.shapes:
        if not getattr(shape, "has_text_frame", False):
            continue
        text = shape.text.strip()
        if text:
            return text
    return ""


def validate_deck_structure(pptx: Path) -> list[tuple[int, int, int, list[str]]]:
    prs = Presentation(str(pptx))
    sw, sh = prs.slide_width, prs.slide_height
    result = []
    for slide in prs.slides:
        oob = zero = 0
        issues: list[str] = []
        for shape in slide.shapes:
            if shape.width <= 0 or shape.height <= 0:
                zero += 1
            if shape.left < 0 or shape.top < 0 or shape.left + shape.width > sw or shape.top + shape.height > sh:
                oob += 1
                issues.append(f"shape {shape.shape_id} outside slide bounds")
        result.append((len(slide.shapes), oob, zero, issues))
    return result


def validate_rendered_pages(pptx: Path, rendered_pages: list[Path], blank_threshold: float = 0.995) -> DeckGateReport:
    prs = Presentation(str(pptx))
    structure = validate_deck_structure(pptx)
    pages: list[PageGate] = []
    slide_count = len(prs.slides)
    for i, path in enumerate(rendered_pages, start=1):
        shape_count, oob, zero, issues = structure[i - 1] if i <= len(structure) else (0, 0, 0, ["missing slide structure"])
        slide = prs.slides[i - 1] if i <= slide_count else None
        role = infer_page_role(i, slide_count, _title_text(slide) if slide else "")
        text_shapes, image_shapes = _shape_stats(slide) if slide else (0, 0)
        with Image.open(path) as im:
            rgb = im.convert("RGB")
            sample = list(rgb.resize((128, 72)).getdata())
            near_white = sum(1 for value in sample if min(value) >= 250) / len(sample)
            width, height = rgb.size
        if near_white >= blank_threshold:
            issues.append(f"rendered page is nearly blank ({near_white:.3f})")
        if oob:
            issues.append(f"{oob} shape(s) exceed slide bounds")
        if zero:
            issues.append(f"{zero} shape(s) have zero/negative size")
        pages.append(PageGate(i, shape_count, oob, zero, width, height, near_white,
                              not issues, issues, role, text_shapes, image_shapes))
    passed = len(structure) == len(rendered_pages) and all(p.passed for p in pages)
    return DeckGateReport(passed, slide_count, pages)
