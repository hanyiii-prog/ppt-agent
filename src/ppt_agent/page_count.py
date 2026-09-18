"""Page Count Engine: how many pages does this content need?

Rules (deterministic, no LLM)
-----------------------------
* fixed overhead: cover (1) + toc (1 when there are >= 2 sections) + closing (1)
* a section's content volume is measured in *char volume* over its blocks
  (heading ~ len, bullets ~ sum of items, table cell ~ 12 CJK chars)
* one standard content page absorbs ~260 CJK chars; tables additionally
  claim one page each (very large tables 1.5)
* density scales the capacity: compact x1.3, standard x1.0, air x0.75
* every estimate carries its assumptions -- never a bare number
"""

from __future__ import annotations

from typing import Any

from .content_ir import ContentDocument

SCHEMA = "page-count/v1"

_DENSITY: dict[str, float] = {"compact": 1.3, "standard": 1.0, "air": 0.75}
_CHARS_PER_PAGE = 260.0
_LARGE_TABLE_ROWS = 8


def _section_volume(blocks: list) -> tuple[float, int]:
    """(char volume, table count) for one section's child blocks."""
    volume = 0.0
    tables = 0
    for block in blocks:
        volume += block.char_volume()
        if block.type == "table":
            tables += 1
            volume -= min(len(block.rows), _LARGE_TABLE_ROWS) * 12  # avoid double count
    return volume, tables


def estimate_page_count(
    document: ContentDocument, *, density: str = "standard"
) -> dict[str, Any]:
    """Estimate the deck size for a ContentDocument (analyzed or raw)."""
    factor = _DENSITY.get(density)
    if factor is None:
        raise ValueError(f"unknown density {density!r}; use compact|standard|air")

    all_sections = document.sections()
    # level-1 headings are the document title (cover material), not sections
    sections = [
        (heading, children)
        for heading, children in all_sections
        if (heading.level or 1) >= 2
    ]
    capacity = _CHARS_PER_PAGE * factor

    per_section: list[dict[str, Any]] = []
    for heading, children in sections:
        volume, tables = _section_volume(children)
        content_pages = int(volume // capacity) + (1 if volume % capacity else 0)
        if volume == 0 and tables == 0:
            content_pages = 1  # an empty section still earns one content page
        per_section.append({
            "title": heading.text,
            "level": heading.level,
            "char_volume": round(volume, 1),
            "tables": tables,
            "content_pages": content_pages + tables,  # big tables claim their own page
            "section_page": 1,
        })

    fixed = {"cover": 1, "toc": 1 if len(per_section) >= 2 else 0, "closing": 1}
    section_total = sum(entry["content_pages"] + entry["section_page"] for entry in per_section)
    total = sum(fixed.values()) + section_total

    return {
        "schema": SCHEMA,
        "density": density,
        "section_count": len(per_section),
        "sections": per_section,
        "fixed_overhead": fixed,
        "section_pages_total": section_total,
        "total": total,
        "assumptions": {
            "chars_per_page_standard": _CHARS_PER_PAGE,
            "density_factor": factor,
            "table_page_policy": "one page per table",
            "toc_policy": "toc page only when sections >= 2",
        },
    }
