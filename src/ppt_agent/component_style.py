"""Resolve a stored component's visual properties from the active DNA.

Components in the store carry structure and relative geometry. When placed
into a deck, their colours, font sizes, line widths and transparency come
from the current template's ``page-kind-dna`` segment -- never from the
component file itself.

This module is the ONLY place where that translation happens.
"""

from __future__ import annotations

from typing import Any

from .page_kind_dna import get_kind_dna


def resolve_component_style(
    component: dict[str, Any],
    kind_dna: dict[str, Any],
    *,
    role: str = "",
) -> dict[str, Any]:
    """Return concrete ``style`` dict for one component slot.

    ``kind_dna`` is the per-kind segment (from ``page_kind_dna.get_kind_dna``).
    ``role`` refines the lookup: "title" gets the title-level size, body slots
    get body-level, decoration gets no text.
    """
    typography = kind_dna.get("typography") or {}
    scale = typography.get("scale_named") or {}
    color = kind_dna.get("color") or {}
    shape = kind_dna.get("shape") or {}
    layout = kind_dna.get("layout") or {}

    style: dict[str, Any] = {}

    if role in ("title", "display"):
        style["font_size"] = scale.get("display") or scale.get("title") or 28.0
        style["color"] = color.get("primary") or color.get("text") or "0A3A52"
    elif role in ("subtitle", "heading"):
        style["font_size"] = scale.get("heading") or scale.get("title") or 20.0
        style["color"] = color.get("text") or "333333"
    elif role in ("body", "card", "list"):
        style["font_size"] = scale.get("body") or 14.0
        style["color"] = color.get("text") or "333333"
    elif role == "caption":
        style["font_size"] = scale.get("caption") or 11.0
        style["color"] = color.get("text_muted") or "888888"
    elif role == "decoration":
        style["fill"] = color.get("primary_soft") or color.get("surface") or "EEEEEE"
        style["line_width"] = (shape.get("line_widths_pt") or [0])[0]
    else:
        style["font_size"] = scale.get("body") or 14.0
        style["color"] = color.get("text") or "333333"

    style["margin_left"] = layout.get("margin_left") or 0.7
    style["margin_top"] = layout.get("margin_top") or 0.5

    return style


def apply_dna_to_slots(
    component: dict[str, Any],
    page_kind_dna: dict[str, Any],
    page_kind: str,
) -> list[dict[str, Any]]:
    """Return the component's slots, each augmented with DNA-resolved style."""
    kind_dna = get_kind_dna(page_kind_dna, page_kind)
    resolved: list[dict[str, Any]] = []
    for slot in component.get("slots") or []:
        role = str(slot.get("role") or "")
        entry = dict(slot)
        entry["style"] = resolve_component_style(component, kind_dna, role=role)
        resolved.append(entry)
    return resolved
