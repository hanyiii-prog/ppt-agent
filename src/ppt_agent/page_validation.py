from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image
from pptx import Presentation


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


@dataclass
class DeckGateReport:
    passed: bool
    slide_count: int
    pages: list[PageGate]

    def to_dict(self) -> dict:
        return {"passed": self.passed, "slide_count": self.slide_count,
                "pages": [asdict(p) for p in self.pages]}


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
    structure = validate_deck_structure(pptx)
    pages: list[PageGate] = []
    for i, path in enumerate(rendered_pages, start=1):
        shape_count, oob, zero, issues = structure[i - 1] if i <= len(structure) else (0, 0, 0, ["missing slide structure"])
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
        pages.append(PageGate(i, shape_count, oob, zero, width, height, near_white, not issues, issues))
    passed = len(structure) == len(rendered_pages) and all(p.passed for p in pages)
    return DeckGateReport(passed, len(structure), pages)
