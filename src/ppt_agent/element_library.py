"""Cross-page element library: which shapes recur and how reusable they are.

Why this exists
---------------
A template's value lives in its repeated vocabulary -- the logo, the header
bar, the card frame, the divider pill. ``page_kinds.ornaments`` answers "what
does every page of this kind share"; the element library answers the broader
"what does this template reuse anywhere", with a single comparable
``reuse_score`` per element.

Identity
--------
Two elements are the same library entry when their normalised signature
matches: element kind, preset geometry, fill kind + resolved rgb, line kind
and a coarse geometry size bucket (0.05 in). Names are *not* part of identity
(templates rename copies), but the most frequent name is reported.

``reuse_score`` in [0, 1] combines occurrence volume and page coverage:
``0.6 * occurrences/max + 0.4 * pages/total_pages``. Deterministic, no LLM.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

SCHEMA = "element-library/v1"

_SIZE_STEP = 0.05


def _fill_key(style: dict[str, Any]) -> str:
    fill = style.get("fill") or {}
    rgb = fill.get("rgb")
    kind = str(fill.get("type") or "none")
    if fill.get("gradient_stops"):
        return "gradient"
    return f"{kind}:{rgb}" if rgb else kind


def _line_key(style: dict[str, Any]) -> str:
    line = style.get("line") or {}
    kind = str((line.get("fill") or {}).get("type") or "none")
    width = line.get("width_pt")
    return f"{kind}:{round(float(width), 1)}" if isinstance(width, (int, float)) else kind


def element_signature(record: dict[str, Any]) -> str:
    """Stable, name-free identity for one element record."""
    geometry = record.get("geometry") or {}
    prst = (geometry.get("prst_geom") or {}).get("type") or "none"
    width = geometry.get("width")
    height = geometry.get("height")
    size_bucket = "none:none"
    if isinstance(width, (int, float)) and isinstance(height, (int, float)):
        size_bucket = f"{round(float(width) / _SIZE_STEP)}x{round(float(height) / _SIZE_STEP)}"
    style = record.get("style") or {}
    return "|".join(
        (
            str(record.get("element") or record.get("type") or "?"),
            str(prst),
            _fill_key(style),
            _line_key(style),
            size_bucket,
        )
    )


def build_element_library(
    deck_dna: dict[str, Any], *, min_occurrences: int = 2
) -> dict[str, Any]:
    """Collect recurring slide-origin elements across the deck.

    Master/layout chrome is excluded: it is already described by
    ``page_kinds.ornaments`` and is inherited rather than re-placed.
    """
    total_pages = len(deck_dna.get("slides") or [])
    seen: dict[str, dict[str, Any]] = {}
    occurrences: Counter[str] = Counter()
    page_sets: dict[str, set[int]] = {}
    names: dict[str, Counter[str]] = {}

    for page in deck_dna.get("slides") or []:
        slide_no = int(page.get("slide") or 0)
        for record in page.get("shapes") or []:
            key = element_signature(record)
            occurrences[key] += 1
            page_sets.setdefault(key, set()).add(slide_no)
            names.setdefault(key, Counter())[str(record.get("name") or "")] += 1
            seen.setdefault(key, record)

    max_occurrences = max(occurrences.values()) if occurrences else 0
    elements: list[dict[str, Any]] = []
    for key, count in occurrences.items():
        if count < min_occurrences:
            continue
        sample = seen[key]
        pages = sorted(page_sets[key])
        coverage = len(pages) / total_pages if total_pages else 0.0
        elements.append({
            "key": key,
            "name": (names[key].most_common(1) or [("", 0)])[0][0] if names[key] else "",
            "element": sample.get("element") or sample.get("type"),
            "occurrences": count,
            "pages": pages,
            "page_coverage": round(coverage, 4),
            "reuse_score": round(
                0.6 * (count / max_occurrences) + 0.4 * coverage, 4
            ) if max_occurrences else 0.0,
            "sample_geometry": sample.get("geometry"),
            "sample_style": {
                "fill": (sample.get("style") or {}).get("fill"),
                "line": (sample.get("style") or {}).get("line"),
            },
            "semantic_role": sample.get("semantic_role"),
        })
    elements.sort(key=lambda item: (-item["reuse_score"], item["key"]))
    return {
        "schema": SCHEMA,
        "total_pages": total_pages,
        "total_slide_elements": sum(occurrences.values()),
        "recurring_elements": len(elements),
        "elements": elements,
    }
