from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from .visual_regression import flatten_pixels


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
    # non-blocking layout findings (e.g. marginal overflow estimates)
    # surfaced by the clone-route auditor; reported but never fail a page
    layout_warnings: list[str] = field(default_factory=list)


@dataclass
class DeckGateReport:
    passed: bool
    slide_count: int
    pages: list[PageGate]
    mode: str = "rendered"

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "slide_count": self.slide_count,
            "mode": self.mode,
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


def _is_zero_size(shape) -> bool:
    """True when a shape's box is genuinely degenerate.

    A straight connector that is perfectly horizontal (or vertical) legitimately
    has zero height (or zero width) in PowerPoint geometry, so only one axis is
    checked for lines: they are broken only when *both* axes collapse.
    """
    width, height = shape.width or 0, shape.height or 0
    if shape.shape_type == MSO_SHAPE_TYPE.LINE:
        return width <= 0 and height <= 0
    return width <= 0 or height <= 0


def validate_deck_structure(pptx: Path) -> list[tuple[int, int, int, list[str]]]:
    prs = Presentation(str(pptx))
    sw, sh = prs.slide_width, prs.slide_height
    result = []
    for slide in prs.slides:
        oob = zero = 0
        issues: list[str] = []
        for shape in slide.shapes:
            if _is_zero_size(shape):
                zero += 1
            if shape.left < 0 or shape.top < 0 or shape.left + shape.width > sw or shape.top + shape.height > sh:
                oob += 1
                issues.append(f"shape {shape.shape_id} outside slide bounds")
        result.append((len(slide.shapes), oob, zero, issues))
    return result


def validate_structural_pages(pptx: Path) -> DeckGateReport:
    """Gate a deck on geometry alone, without rasterisation.

    Hosts without a rasteriser degrade to this gate instead of losing the page
    gate entirely: bounds, zero-size shapes and empty slides are still caught.
    """
    prs = Presentation(str(pptx))
    structure = validate_deck_structure(pptx)
    slide_count = len(prs.slides)
    pages: list[PageGate] = []
    for index, (shape_count, oob, zero, issues) in enumerate(structure, start=1):
        slide = prs.slides[index - 1] if index <= slide_count else None
        role = infer_page_role(index, slide_count, _title_text(slide) if slide else "")
        text_shapes, image_shapes = _shape_stats(slide) if slide else (0, 0)
        problems = list(issues)
        if shape_count == 0:
            problems.append("slide contains no shapes")
        pages.append(
            PageGate(index, shape_count, oob, zero, 0, 0, 0.0, not problems, problems,
                     role, text_shapes, image_shapes)
        )
    passed = bool(pages) and all(page.passed for page in pages)
    return DeckGateReport(passed, slide_count, pages, mode="structural")


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
            sample = flatten_pixels(rgb.resize((128, 72)))
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
