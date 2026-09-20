"""Per-page-kind DNA extraction (schema ``page-kind-dna/v1``).

Why this exists
---------------
The global ``design_dna`` aggregates over every slide in the template. A cover
page's typography and a content page's spacing rhythm are different design
languages; using the global aggregate blurs them. This module splits the
v1.0 design DNA into per-kind segments so generation can pick the right
vocabulary for each page it draws.

Kinds
-----
``cover``, ``toc``, ``section``, ``content``, ``closing`` (the five fixed
kinds from the presentation plan) plus ``special`` subtypes detected from
content shape:

* ``quote``      -- page dominated by quote blocks
* ``image_full`` -- page dominated by a large picture
* ``chart``      -- page dominated by a chart / table
* ``divider``    -- transitional page between major sections (lighter than section)

Output structure::

    {
      "schema": "page-kind-dna/v1",
      "template_fingerprint": "abc123...",
      "kinds": {
        "cover":   {"shape": ..., "layout": ..., "typography": ..., "color": ...},
        "toc":     {...},
        "section": {...},
        "content": {...},
        "closing": {...},
        "special": {
          "quote":      {...},
          "image_full": {...},
          "chart":      {...},
          "divider":    {...}
        }
      }
    }

Every segment is derived from ONLY that kind's slides + their layout/master
inheritance -- never mixed with other kinds' records.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

SCHEMA = "page-kind-dna/v1"

BASE_KINDS: tuple[str, ...] = ("cover", "toc", "section", "content", "closing")
SPECIAL_KINDS: tuple[str, ...] = ("quote", "image_full", "chart", "divider")
ALL_KINDS: tuple[str, ...] = BASE_KINDS + SPECIAL_KINDS


def _kind_of(page: dict[str, Any]) -> str:
    """Read the page kind from a deck-dna slide entry."""
    kind = str(page.get("kind") or page.get("page_kind") or "content").lower()
    if kind in BASE_KINDS:
        return kind
    return "content"


def _detect_special(page: dict[str, Any]) -> str | None:
    """Detect a special subtype from a content page's shape composition."""
    layers = page.get("layers") or []
    if not layers:
        return None

    roles: Counter[str] = Counter()
    for record in layers:
        roles[str(record.get("semantic_role") or "unknown")] += 1
        element = str(record.get("element") or record.get("type") or "").lower()
        if element in ("pic", "chart"):
            roles[f"_{element}"] += 1

    total = sum(1 for r in roles if not r.startswith("_"))
    if total == 0:
        return None

    if roles.get("_chart", 0) >= 1 or sum(1 for r in layers if str(r.get("element") or "").lower() == "graphicFrame") >= 1:
        return "chart"

    pics = roles.get("_pic", 0)
    if pics >= 1:
        largest_pic = 0.0
        for record in layers:
            if str(record.get("element") or "").lower() != "pic":
                continue
            geom = record.get("geometry") or {}
            w = geom.get("width") or 0
            h = geom.get("height") or 0
            slide_area = (page.get("slide_width") or 13.333) * (page.get("slide_height") or 7.5)
            if slide_area > 0:
                largest_pic = max(largest_pic, (w * h) / slide_area)
        if largest_pic > 0.5:
            return "image_full"

    if roles.get("decoration", 0) / total < 0.2 and roles.get("title", 0) >= 1 and total <= 3:
        return "quote"

    return None


def _extract_segment(records: list[dict[str, Any]], slide_area: float) -> dict[str, Any]:
    """Derive a per-kind DNA segment from slide-origin records."""
    from .design_dna import (
        _hex_of, _luminance, _saturation, _hue,
    )

    fill_census: Counter[str] = Counter()
    line_widths: Counter[float] = Counter()
    font_sizes: Counter[float] = Counter()
    font_names: Counter[str] = Counter()
    margins_top: Counter[float] = Counter()
    margins_bottom: Counter[float] = Counter()
    margins_left: Counter[float] = Counter()
    margins_right: Counter[float] = Counter()

    for record in records:
        style = record.get("style") or {}
        fill = style.get("fill") or {}
        rgb = _hex_of(fill.get("rgb"))
        if rgb:
            fill_census[rgb] += 1

        line = style.get("line") or {}
        width = line.get("width_pt")
        if isinstance(width, (int, float)):
            line_widths[float(width)] += 1

        text = record.get("text") or {}
        if isinstance(text, dict):
            for font in text.get("fonts") or []:
                size = font.get("size_pt")
                if isinstance(size, (int, float)) and size > 0:
                    font_sizes[float(size)] += 1
                name = font.get("name")
                if name:
                    font_names[str(name)] += 1

        geom = record.get("geometry") or {}
        left, top = geom.get("left"), geom.get("top")
        right = (left + geom.get("width", 0)) if isinstance(left, (int, float)) else None
        bottom = (top + geom.get("height", 0)) if isinstance(top, (int, float)) else None
        if isinstance(top, (int, float)):
            margins_top[round(float(top), 2)] += 1
        if isinstance(bottom, (int, float)):
            margins_bottom[round(float(7.5 - bottom), 2)] += 1
        if isinstance(left, (int, float)):
            margins_left[round(float(left), 2)] += 1
        if isinstance(right, (int, float)):
            margins_right[round(float(13.333 - right), 2)] += 1

    ranked_sizes = sorted(font_sizes, reverse=True)
    type_scale: dict[str, float] = {}
    levels = ("display", "title", "heading", "body", "caption")
    for level, size in zip(levels, ranked_sizes[:5]):
        type_scale[level] = size

    chromatics: list[str] = []
    neutrals: list[str] = []
    for rgb, _count in fill_census.most_common(12):
        if _saturation(rgb) > 0.25:
            chromatics.append(rgb)
        else:
            neutrals.append(rgb)
    chromatics.sort(key=lambda c: -fill_census.get(c, 0))
    neutrals.sort(key=_luminance)

    return {
        "slide_count": len({r.get("_page") for r in records if r.get("_page")}),
        "record_count": len(records),
        "typography": {
            "scale_named": type_scale,
            "families": [name for name, _c in font_names.most_common(5)],
        },
        "color": {
            "primary": chromatics[0] if chromatics else None,
            "accent": chromatics[1] if len(chromatics) > 1 else None,
            "text": neutrals[-1] if neutrals else None,
            "surface": neutrals[0] if neutrals else None,
            "census": [{"rgb": rgb, "count": c} for rgb, c in fill_census.most_common(8)],
        },
        "shape": {
            "line_widths_pt": sorted(line_widths),
            "fill_kinds": dict(Counter(
                str((r.get("style") or {}).get("fill", {}).get("type") or "none")
                for r in records
            )),
        },
        "layout": {
            "margin_top": _mode(margins_top),
            "margin_bottom": _mode(margins_bottom),
            "margin_left": _mode(margins_left),
            "margin_right": _mode(margins_right),
        },
    }


def _mode(counter: Counter[float]) -> float | None:
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def build_page_kind_dna(
    deck_dna: dict[str, Any],
    design_dna: dict[str, Any],
    *,
    template_fingerprint: str = "",
) -> dict[str, Any]:
    """Split a ``template-dna/v1.0`` payload into per-kind DNA segments.

    ``deck_dna`` is the raw v0.4/v1.0 payload (with ``slides`` entries);
    ``design_dna`` is the aggregated v1.0 output (for the fingerprint if not
    given explicitly).
    """
    if not isinstance(deck_dna, dict) or "slides" not in deck_dna:
        raise ValueError("build_page_kind_dna expects a template-dna payload")

    fp = template_fingerprint or design_dna.get("template_fingerprint") or ""
    size = (deck_dna.get("presentation") or {}).get("slide_size_inches") or {}
    slide_area = float(size.get("width") or 13.333) * float(size.get("height") or 7.5)

    grouped: dict[str, list[dict[str, Any]]] = {kind: [] for kind in ALL_KINDS}
    special_detected: set[str] = set()

    for page in deck_dna.get("slides") or []:
        kind = _kind_of(page)
        page_no = page.get("slide") or 0
        records = [
            dict(record, _page=page_no)
            for record in page.get("layers") or []
            if record.get("origin") == "slide"
        ]

        if kind == "content":
            special = _detect_special(page)
            if special:
                grouped[special].extend(records)
                special_detected.add(special)

        grouped[kind].extend(records)

    kinds: dict[str, Any] = {}
    for kind in BASE_KINDS:
        kinds[kind] = _extract_segment(grouped[kind], slide_area)

    special: dict[str, Any] = {}
    for kind in SPECIAL_KINDS:
        if kind in special_detected:
            special[kind] = _extract_segment(grouped[kind], slide_area)
    if special:
        kinds["special"] = special

    return {
        "schema": SCHEMA,
        "template_fingerprint": fp,
        "kinds": kinds,
    }


def get_kind_dna(
    page_kind_dna: dict[str, Any], kind: str
) -> dict[str, Any]:
    """Look up one kind's DNA segment; falls back to content for unknown kinds."""
    kinds = page_kind_dna.get("kinds") or {}
    if kind in kinds:
        return kinds[kind]
    if kind in SPECIAL_KINDS and "special" in kinds and kind in kinds["special"]:
        return kinds["special"][kind]
    return kinds.get("content") or {}
