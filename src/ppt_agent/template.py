from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

EMU_PER_INCH = 914400


def analyze_pptx(path: str | Path) -> dict[str, Any]:
    """Extract deterministic, dependency-light Template DNA from a PPTX.

    This is intentionally descriptive rather than generative: it records slide
    dimensions, common fonts/sizes/colors and per-slide structural statistics.
    """
    try:
        from pptx import Presentation as PptxPresentation
    except ImportError as exc:
        raise RuntimeError(
            "python-pptx is required for PPTX analysis; install with "
            "pip install 'ppt-agent[pptx]'"
        ) from exc

    prs = PptxPresentation(str(path))
    fonts: Counter[str] = Counter()
    font_sizes: Counter[float] = Counter()
    fills: Counter[str] = Counter()
    shape_types: Counter[str] = Counter()
    slide_stats: list[dict[str, Any]] = []

    for slide_no, slide in enumerate(prs.slides, 1):
        text_shapes = images = charts = tables = 0
        for shape in slide.shapes:
            shape_types[str(shape.shape_type)] += 1
            if getattr(shape, "has_text_frame", False):
                text_shapes += 1
                for paragraph in shape.text_frame.paragraphs:
                    for run in paragraph.runs:
                        if run.font.name:
                            fonts[run.font.name] += 1
                        if run.font.size:
                            font_sizes[round(run.font.size.pt, 1)] += 1
                try:
                    rgb = shape.fill.fore_color.rgb
                    if rgb:
                        fills[str(rgb)] += 1
                except (AttributeError, ValueError, TypeError):
                    pass
            if str(shape.shape_type) == "13":
                images += 1
            if getattr(shape, "has_chart", False):
                charts += 1
            if getattr(shape, "has_table", False):
                tables += 1

        slide_stats.append(
            {
                "slide": slide_no,
                "shapes": len(slide.shapes),
                "text_shapes": text_shapes,
                "images": images,
                "charts": charts,
                "tables": tables,
            }
        )

    return {
        "schema": "template-dna/v0.1",
        "source": str(path),
        "slide_size_inches": {
            "width": round(prs.slide_width / EMU_PER_INCH, 3),
            "height": round(prs.slide_height / EMU_PER_INCH, 3),
        },
        "slide_count": len(prs.slides),
        "fonts": fonts.most_common(12),
        "font_sizes_pt": font_sizes.most_common(12),
        "fills_rgb": fills.most_common(12),
        "shape_types": shape_types,
        "slide_stats": slide_stats,
    }
