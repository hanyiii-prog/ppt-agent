"""Design DNA aggregation (schema ``template-dna/v1.0``).

Why this exists
---------------
``template-dna/v0.4`` records per-shape OOXML evidence, but it does not
*name* anything. A consumer that asks "what corner radius does this template
use?", "how wide is the content margin?", "which sizes form the type scale?"
still has to re-derive answers from hundreds of raw shape records.

What this module produces
-------------------------
``build_design_dna(deck_dna)`` takes a ``template-dna/v0.4`` dict (as produced
by ``page_dna.extract_deck_dna``) and returns a ``template-dna/v1.0`` dict:
every v0.4 key is preserved unchanged and a ``design_dna`` segment is added:

``design_dna.shape``
    Named shape language: corner-radius census, line widths, border census,
    effects census (shadow / glow), opacity census, fill-kind census.

``design_dna.layout``
    Per-page-kind content margins, dominant column structure, gutter and the
    safe area (union of non-bleed content boxes) -- all derived from the
    geometry that v0.4 already captured.

``design_dna.typography``
    Font families plus a *named* type scale (display / title / heading / body /
    caption) clustered from the size census.

``design_dna.color``
    Ten named colour classes (primary / primary_deep / primary_soft / accent /
    text / text_muted / line / surface / positive / negative) resolved from the
    theme scheme, the dominant palette and luminance/saturation reasoning.

Nothing here re-parses OOXML: v1.0 is a pure aggregation layer over v0.4, so
the extraction path stays single-sourced.
"""

from __future__ import annotations

import colorsys
from collections import Counter
from typing import Any

SCHEMA = "template-dna/v1.0"

# Named colour classes the colour rules speak about.
COLOR_CLASSES: tuple[str, ...] = (
    "primary", "primary_deep", "primary_soft", "accent",
    "text", "text_muted", "line", "surface", "positive", "negative",
)

# Named type-scale levels, large -> small.
TYPE_SCALE_LEVELS: tuple[str, ...] = (
    "display", "title", "heading", "body", "caption",
)

_CORNER_PRSTS = frozenset({"roundRect", "round2SameRect", "round1Rect", "round2DiagRect", "ellipse"})

_GLYPH_AREA = 0.018  # a shape smaller than this share of the slide is "small"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _iter_records(deck_dna: dict[str, Any]) -> list[dict[str, Any]]:
    """Every element record in the deck: slides layers, master shapes (recursive)."""
    out: list[dict[str, Any]] = []
    for page in deck_dna.get("slides") or []:
        out.extend(page.get("layers") or [])
    for master in deck_dna.get("masters") or []:
        stack = list(master.get("shapes") or [])
        while stack:
            record = stack.pop(0)
            out.append(record)
            stack.extend(record.get("children") or [])
    return out


def _records_by_kind(deck_dna: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Slide-origin element records per page kind.

    Master/layout chrome is excluded on purpose: layout margins, columns and
    the safe area describe where the template *places content*, not where the
    inherited master happens to carry placeholders.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for page in deck_dna.get("slides") or []:
        grouped.setdefault(str(page.get("kind")), []).extend(
            record
            for record in page.get("layers") or []
            if record.get("origin") == "slide"
        )
    return grouped


def _hex_of(value: Any) -> str | None:
    """Normalise any colour-ish value to an uppercase 6-digit hex string."""
    if not isinstance(value, str):
        return None
    text = value.strip().lstrip("#").upper()
    if len(text) == 8:  # ARGB
        text = text[2:]
    if len(text) == 6 and all(c in "0123456789ABCDEF" for c in text):
        return text
    return None


def _rgb_tuple(hex_value: str) -> tuple[float, float, float]:
    return (
        int(hex_value[0:2], 16) / 255.0,
        int(hex_value[2:4], 16) / 255.0,
        int(hex_value[4:6], 16) / 255.0,
    )


def _hex_from_rgb(rgb: tuple[float, float, float]) -> str:
    return "{:02X}{:02X}{:02X}".format(*(max(0, min(255, round(c * 255))) for c in rgb))


def _luminance(hex_value: str) -> float:
    r, g, b = _rgb_tuple(hex_value)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _saturation(hex_value: str) -> float:
    h, l, s = colorsys.rgb_to_hls(*_rgb_tuple(hex_value))
    return s


def _hue(hex_value: str) -> float:
    h, _l, _s = colorsys.rgb_to_hls(*_rgb_tuple(hex_value))
    return h


def _bbox(record: dict[str, Any]) -> tuple[float, float, float, float] | None:
    geom = record.get("geometry") or {}
    left, top = geom.get("left"), geom.get("top")
    width, height = geom.get("width"), geom.get("height")
    if None in (left, top, width, height):
        return None
    return (float(left), float(top), float(width), float(height))


def _round_to(value: float, step: float) -> float:
    return round(round(value / step) * step, 4)


def _top_clusters(counter: Counter[float], *, min_count: int = 2, top: int = 3) -> list[dict[str, Any]]:
    return [
        {"value": value, "count": count}
        for value, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        if count >= min_count
    ][:top]


# --------------------------------------------------------------------------- #
# shape DNA
# --------------------------------------------------------------------------- #
def _shape_dna(records: list[dict[str, Any]], slide_area: float) -> dict[str, Any]:
    corners: Counter[float] = Counter()
    corner_sources: Counter[str] = Counter()
    line_widths: Counter[float] = Counter()
    borders = Counter()
    effects: Counter[str] = Counter()
    alphas: Counter[float] = Counter()
    fill_kinds: Counter[str] = Counter()
    geometry_kinds: Counter[str] = Counter()

    for record in records:
        style = record.get("style") or {}
        geometry = record.get("geometry") or {}
        prst = style.get("geometry_kind") or (geometry.get("prst_geom") or {}).get("type")
        if prst:
            geometry_kinds[str(prst)] += 1
        if prst in _CORNER_PRSTS:
            adj = ((geometry.get("prst_geom") or {}).get("avLst") or {})
            values = [
                float(v) for v in adj.values() if isinstance(v, (int, float))
            ] or [16667.0]  # roundRect default when no adj is declared
            for value in values:
                corners[_round_to(value / 100000.0, 0.01)] += 1
                corner_sources[str(prst)] += 1
        line = style.get("line") or {}
        width = line.get("width_pt")
        if isinstance(width, (int, float)) and width > 0:
            line_widths[_round_to(float(width), 0.25)] += 1
        borders["with_border" if line.get("fill") not in (None, {}, {"type": "none"}) else "borderless"] += 1
        for effect in style.get("effects") or []:
            effects[str((effect or {}).get("type") or "unknown")] += 1
        fill = style.get("fill") or {}
        fill_kinds[str(fill.get("type") or "none")] += 1
        alpha = fill.get("alpha")
        if isinstance(alpha, (int, float)) and alpha < 100:
            alphas[_round_to(float(alpha), 1.0)] += 1

    return {
        "corner_radius": {
            "census": _top_clusters(corners, min_count=1, top=5),
            "sources": dict(corner_sources),
        },
        "line_widths_pt": _top_clusters(line_widths, min_count=1, top=5),
        "borders": dict(borders),
        "effects": dict(effects),
        "opacity": {"translucent_shapes": sum(alphas.values()), "alpha_values": _top_clusters(alphas, min_count=1, top=5)},
        "fill_kinds": dict(fill_kinds),
        "geometry_kinds": dict(geometry_kinds.most_common(12)),
    }


# --------------------------------------------------------------------------- #
# layout DNA
# --------------------------------------------------------------------------- #
def _page_margins(records: list[dict[str, Any]], slide_w: float, slide_h: float) -> dict[str, Any]:
    boxes = [box for record in records if (box := _bbox(record))]
    content = [
        (left, top, width, height)
        for left, top, width, height in boxes
        if width < slide_w * 0.92 and height < slide_h * 0.92
    ]
    if not content:
        return {}
    lefts = [left for left, _t, _w, _h in content]
    tops = [top for _l, top, _w, _h in content]
    rights = [left + width for left, _t, width, _h in content]
    bottoms = [_t + height for _l, _t, _w, height in content]
    return {
        "left_in": round(min(lefts), 3),
        "top_in": round(min(tops), 3),
        "right_in": round(slide_w - max(rights), 3),
        "bottom_in": round(slide_h - max(bottoms), 3),
        "content_boxes": len(content),
    }


def _columns(records: list[dict[str, Any]], slide_w: float) -> dict[str, Any]:
    """Cluster content-box left edges; the surviving clusters suggest columns."""
    boxes = [box for record in records if (box := _bbox(record))]
    content = [left for left, _t, width, _h in boxes if width < slide_w * 0.92]
    if not content:
        return {}
    content.sort()
    clusters: list[list[float]] = [[content[0]]]
    for left in content[1:]:
        if left - clusters[-1][-1] <= 0.25:
            clusters[-1].append(left)
        else:
            clusters.append([left])
    stable = [cluster for cluster in clusters if len(cluster) >= 2]
    if not stable:
        return {"column_count": 1, "left_edges_in": []}
    lefts = [round(sorted(cluster)[0], 3) for cluster in stable]
    return {
        "column_count": len(stable),
        "left_edges_in": lefts,
    }


def _layout_dna(
    grouped: dict[str, list[dict[str, Any]]], slide_w: float, slide_h: float
) -> dict[str, Any]:
    per_kind: dict[str, Any] = {}
    for kind, records in sorted(grouped.items()):
        margins = _page_margins(records, slide_w, slide_h)
        per_kind[kind] = {
            "margins": margins,
            "columns": _columns(records, slide_w),
        }
    # safe area: union bbox of non-bleed content across the whole deck
    content = [
        box
        for record in _iter_records(_safe_area_view(grouped))
        if (box := _bbox(record)) and box[2] < slide_w * 0.92 and box[3] < slide_h * 0.92
    ]
    safe_area = {}
    if content:
        safe_area = {
            "left_in": round(min(b[0] for b in content), 3),
            "top_in": round(min(b[1] for b in content), 3),
            "right_in": round(slide_w - max(b[0] + b[2] for b in content), 3),
            "bottom_in": round(slide_h - max(b[1] + b[3] for b in content), 3),
        }
    return {"per_kind": per_kind, "safe_area": safe_area}


def _safe_area_view(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        "slides": [{"kind": kind, "layers": records} for kind, records in grouped.items()],
        "masters": [],
    }


# --------------------------------------------------------------------------- #
# typography DNA
# --------------------------------------------------------------------------- #
def _typography_dna(deck_dna: dict[str, Any]) -> dict[str, Any]:
    stats = deck_dna.get("global_style_statistics") or {}
    fonts = Counter({str(name): count for name, count in (stats.get("fonts") or [])})
    sizes = Counter({float(size): count for size, count in (stats.get("font_sizes_pt") or [])})

    named: dict[str, float | None] = {level: None for level in TYPE_SCALE_LEVELS}
    frequent = [size for size, count in sizes.most_common() if count >= 1]
    if frequent:
        # ordered assignment: display = largest, then title, heading, ... -- the
        # scale is monotonic by construction, never a shuffled subset.
        ranked = sorted(set(frequent), reverse=True)
        for level, size in zip(TYPE_SCALE_LEVELS, ranked):
            named[level] = float(size)

    families = [name for name, _count in fonts.most_common(8)]
    theme_fonts = ((deck_dna.get("theme") or {}).get("font_scheme") or {})
    return {
        "families": families,
        "major_font": (theme_fonts.get("majorFace") or {}).get("latin") or (families or [None])[0],
        "minor_font": (theme_fonts.get("minorFace") or {}).get("latin") or (families or [None])[0],
        "scale_named": named,
        "size_census": [
            {"size_pt": size, "count": count} for size, count in sizes.most_common(12)
        ],
    }


# --------------------------------------------------------------------------- #
# colour DNA
# --------------------------------------------------------------------------- #
def _color_dna(deck_dna: dict[str, Any]) -> dict[str, Any]:
    theme_colors = dict((deck_dna.get("theme") or {}).get("colors") or {})
    palette = deck_dna.get("dominant_palette") or {}
    records = _iter_records(deck_dna)

    rgb_census: Counter[str] = Counter()
    for record in records:
        fill = (record.get("style") or {}).get("fill") or {}
        hex_value = _hex_of(fill.get("rgb"))
        if hex_value:
            rgb_census[hex_value] += 1

    scheme_values: list[str] = []
    for value in theme_colors.values():
        hex_value = _hex_of(value)
        if hex_value:
            scheme_values.append(hex_value)

    pool: list[str] = []
    for entry in palette.get("colors") or []:
        hex_value = _hex_of(entry.get("rgb") if isinstance(entry, dict) else entry)
        if hex_value:
            pool.append(hex_value)
    for hex_value, _count in rgb_census.most_common(8):
        pool.append(hex_value)

    neutrals = [c for c in pool if _saturation(c) <= 0.25]
    chromatics = sorted(
        (c for c in pool if _saturation(c) > 0.25),
        key=lambda c: -(rgb_census.get(c, 0) + pool.count(c)),
    )
    dark_neutrals = sorted(neutrals, key=_luminance)
    light_neutrals = sorted(neutrals, key=_luminance, reverse=True)

    primary = chromatics[0] if chromatics else None
    accent = next((c for c in chromatics[1:] if primary and _hue(c) != _hue(primary)), None)
    named: dict[str, str | None] = {name: None for name in COLOR_CLASSES}
    named["primary"] = primary
    named["accent"] = accent
    named["text"] = dark_neutrals[-1] if dark_neutrals else None
    named["text_muted"] = dark_neutrals[-2] if len(dark_neutrals) >= 2 else None
    named["surface"] = light_neutrals[0] if light_neutrals else None
    named["line"] = light_neutrals[1] if len(light_neutrals) >= 2 else None
    named["primary_soft"] = next(
        (c for c in pool if primary and c != primary and _hue(c) == _hue(primary) and _luminance(c) > 0.7),
        None,
    )
    named["primary_deep"] = next(
        (c for c in pool if primary and c != primary and _hue(c) == _hue(primary) and _luminance(c) < 0.35),
        None,
    )
    named["positive"] = next((c for c in chromatics if 0.25 < _hue(c) < 0.52), None)
    named["negative"] = next((c for c in chromatics if _hue(c) < 0.05 or _hue(c) > 0.92), None)

    return {
        "named": named,
        "scheme": {key: _hex_of(value) for key, value in theme_colors.items()},
        "census": [
            {"rgb": rgb, "count": count} for rgb, count in rgb_census.most_common(12)
        ],
    }


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def build_design_dna(deck_dna: dict[str, Any]) -> dict[str, Any]:
    """Aggregate a ``template-dna/v0.4`` deck dict into a ``v1.0`` dict.

    Every v0.4 key is preserved; ``design_dna`` is added and the schema stamp
    is upgraded. Idempotent: passing a v1.0 dict re-derives the segment.
    """
    if not isinstance(deck_dna, dict) or "slides" not in deck_dna:
        raise ValueError("build_design_dna expects an extract_deck_dna payload")

    size = (deck_dna.get("presentation") or {}).get("slide_size_inches") or {}
    slide_w = float(size.get("width") or 13.333)
    slide_h = float(size.get("height") or 7.5)
    slide_area = slide_w * slide_h

    grouped = _records_by_kind(deck_dna)
    result = dict(deck_dna)
    result["schema"] = SCHEMA
    result["design_dna"] = {
        "shape": _shape_dna(_iter_records(deck_dna), slide_area),
        "layout": _layout_dna(grouped, slide_w, slide_h),
        "typography": _typography_dna(deck_dna),
        "color": _color_dna(deck_dna),
    }
    return result
