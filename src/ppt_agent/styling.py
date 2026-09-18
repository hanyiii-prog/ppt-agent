"""Shared style conventions for every renderer.

Both the native PPTX engine and the HTML visual engine must read the same IR
style dictionary the same way. Anything renderer-specific stays in its own
module; anything both need lives here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .ir import Component, Slide

EMU_PER_INCH = 914400
DEFAULT_SLIDE_W_IN = 13.333
DEFAULT_SLIDE_H_IN = 7.5
MARGIN_IN = 0.7
FLOW_GAP_IN = 0.16

# Components that carry text rather than geometry.
TEXT_COMPONENT_TYPES: frozenset[str] = frozenset({
    "text", "paragraph", "title", "subtitle", "body", "bullet",
    "caption", "label", "heading", "quote",
})

# Slide purposes whose first component is treated as a full-bleed title.
TITLE_PURPOSES: frozenset[str] = frozenset({"cover", "closing", "title", "section"})

_ALIGNMENTS: frozenset[str] = frozenset({"left", "center", "right", "justify"})


def normalize_color(value: Any) -> str | None:
    """Return an uppercase 6-digit hex colour without `#`, or None."""
    if value is None:
        return None
    text = str(value).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in text):
        return None
    return text.upper()


def normalize_opacity(fill: Any) -> float | None:
    """Read opacity from an IR fill dictionary.

    Accepts `opacity` (0-1), `transparency` (0-1, inverted) and `alpha`
    (either 0-1 or OOXML 0-100000). Explicit `opacity` wins, then
    `transparency`, then `alpha`.
    """
    if not isinstance(fill, dict):
        return None
    if isinstance(fill.get("opacity"), (int, float)):
        return _clamp(fill["opacity"])
    if isinstance(fill.get("transparency"), (int, float)):
        return _clamp(1.0 - float(fill["transparency"]))
    alpha = fill.get("alpha")
    if isinstance(alpha, (int, float)):
        value = float(alpha)
        if value > 1:
            value /= 100000.0
        return _clamp(value)
    return None


def normalize_alignment(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text if text in _ALIGNMENTS else None


def font_style_of(component: Any) -> dict[str, Any]:
    """Extract the `style.font` sub-dictionary of a component, or an empty dict."""
    style = getattr(component, "style", None)
    if not isinstance(style, dict):
        return {}
    font = style.get("font")
    return font if isinstance(font, dict) else {}


def text_of(component: Any) -> str:
    """Text carried by a component, falling back to `data.text`."""
    text = getattr(component, "text", None)
    if text is None:
        data = getattr(component, "data", None)
        if isinstance(data, dict):
            text = data.get("text")
    return "" if text is None else str(text)


def slide_size_inches(presentation: Any) -> tuple[float, float]:
    theme = getattr(presentation, "theme", None)
    theme = theme if isinstance(theme, dict) else {}
    size = theme.get("slide_size_inches")
    if isinstance(size, dict):
        width, height = size.get("width"), size.get("height")
        if isinstance(width, (int, float)) and isinstance(height, (int, float)) and width > 0 and height > 0:
            return float(width), float(height)
    if isinstance(size, (list, tuple)) and len(size) == 2:
        width, height = size
        if isinstance(width, (int, float)) and isinstance(height, (int, float)) and width > 0 and height > 0:
            return float(width), float(height)
    return DEFAULT_SLIDE_W_IN, DEFAULT_SLIDE_H_IN


def has_geometry(component: Any) -> bool:
    return all(
        isinstance(getattr(component, key, None), (int, float)) for key in ("x", "y", "w", "h")
    )


# --- Shared layout algorithm ---------------------------------------------
# Both the native PPTX engine and the HTML visual engine resolve component
# geometry through resolve_layout(). Diverging layout code would make cross
# engine comparison meaningless, so this is deliberately the only copy.
@dataclass(frozen=True)
class LayoutBox:
    component: Any
    x: float
    y: float
    w: float
    h: float
    font_pt: float
    absolute: bool


def default_font_size(component: Any, slide_purpose: str) -> float:
    font = font_style_of(component)
    if isinstance(font.get("size_pt"), (int, float)):
        return float(font["size_pt"])
    if (getattr(component, "type", "") or "").lower() in {"title", "heading"}:
        return 36.0
    if slide_purpose in TITLE_PURPOSES:
        return 28.0
    return 20.0


def estimate_flow_height(component: Any, width_in: float, default_size_pt: float) -> float:
    """Estimate the height a flowing text block needs, in inches."""
    text = text_of(component)
    chars_per_line = max(12.0, width_in * 11.0)
    lines = 0
    for segment in text.split("\n"):
        lines += max(1, int(len(segment) / chars_per_line) + (1 if len(segment) % chars_per_line else 0))
    lines = max(1, lines)
    line_height = max(0.32, default_size_pt / 72.0 * 1.35)
    return round(lines * line_height + 0.12, 3)


def resolve_layout(
    slide: "Slide",
    width_in: float,
    height_in: float,
    *,
    engine: str = "legacy",
    report: dict[str, Any] | None = None,
) -> list[LayoutBox]:
    """Resolve every component of a slide into an absolute box, in inches.

    Components with explicit geometry are placed verbatim. Components without
    geometry flow top-down from a purpose-dependent start cursor.

    ``engine`` selects the flow stage *inside this single algorithm* (red
    line 1: there is exactly one layout algorithm):

    * ``legacy`` (default) -- the pre-V2.1 behaviour, byte-identical (guarded
      by tests/test_layout_solver.py::test_legacy_engine_is_byte_identical);
    * ``solver`` -- the same initial resolution passed through the batch 3.D
      upgrade stages (glyph-aware re-measure, collision push-down, grid snap,
      bounded overflow shrink). Absolute geometry is verbatim in both engines.
      A ``report`` dict, when given, receives the solver metrics.
    """
    purpose = (getattr(slide, "purpose", None) or "content").lower()
    content_width = width_in - 2 * MARGIN_IN
    cursor = 0.6 if purpose not in TITLE_PURPOSES else 1.6
    boxes: list[LayoutBox] = []

    for index, component in enumerate(getattr(slide, "components", []) or []):
        font_pt = default_font_size(component, purpose)
        if has_geometry(component):
            boxes.append(LayoutBox(
                component,
                float(component.x),
                float(component.y),
                max(float(component.w), 0.05),
                max(float(component.h), 0.05),
                font_pt,
                True,
            ))
            continue
        if purpose in TITLE_PURPOSES and index == 0:
            font_pt = max(font_pt, 36.0)
            height = max(estimate_flow_height(component, content_width, font_pt), 0.9)
            boxes.append(LayoutBox(
                component, MARGIN_IN, (height_in - height) / 2, content_width, height, font_pt, False
            ))
            continue
        height = estimate_flow_height(component, content_width, font_pt)
        boxes.append(LayoutBox(component, MARGIN_IN, cursor, content_width, height, font_pt, False))
        cursor += height + FLOW_GAP_IN

    if engine == "legacy":
        return boxes
    if engine == "solver":
        from .layout.layout_solver import solve  # lazy: styling must not import layout eagerly

        solved, solver_report = solve(boxes, width_in, height_in)
        if isinstance(report, dict):
            report.update(solver_report)
        return solved
    raise ValueError(f"unknown layout engine {engine!r}; use 'legacy' or 'solver'")


def group_children(component: Any) -> list[Any]:
    """Children preserved by the OOXML fidelity layer for a group component."""
    data = getattr(component, "data", None)
    data = data if isinstance(data, dict) else {}
    fidelity = data.get("fidelity")
    fidelity = fidelity if isinstance(fidelity, dict) else {}
    children = fidelity.get("children")
    if not isinstance(children, list) or not children:
        return []
    from .dna_to_ir import _component as dna_component

    provenance = getattr(component, "provenance", None) or []
    source = provenance[0].source_id if provenance else "render"
    return [dna_component(child, source) for child in children if isinstance(child, dict)]


def _clamp(value: Any) -> float:
    return max(0.0, min(1.0, float(value)))
