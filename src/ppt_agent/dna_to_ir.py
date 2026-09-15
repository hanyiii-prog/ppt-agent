from __future__ import annotations

from typing import Any

from .ir import Component, Presentation, Provenance, Slide


_ROLE_TO_PURPOSE = {
    "first": "cover",
    "last": "closing",
    "body": "content",
}


def _component_type(shape: dict[str, Any]) -> str:
    """Map Template DNA shape types to the small, stable IR vocabulary."""
    shape_type = str(shape.get("type") or "unknown").lower()
    if "text" in shape_type:
        return "text"
    if "picture" in shape_type or "image" in shape_type:
        return "image"
    if "table" in shape_type:
        return "table"
    if "chart" in shape_type:
        return "chart"
    if shape.get("is_group"):
        return "group"
    return "shape"


def _text_value(shape: dict[str, Any]) -> str | None:
    text = shape.get("text")
    if isinstance(text, str):
        return text
    if not isinstance(text, dict):
        return None
    for key in ("text", "plain_text", "value"):
        value = text.get(key)
        if isinstance(value, str):
            return value
    return None


def _component(shape: dict[str, Any], source: str) -> Component:
    geometry = shape.get("geometry") or {}
    style = shape.get("style") or {}
    # Keep the complete source record under data.  IR stays intentionally small,
    # while DNA fidelity (alpha, z-order, parent/children, raw OOXML metadata, etc.)
    # remains available for later rendering/repair passes.
    fidelity = {
        "z_index": shape.get("z_index", shape.get("z_order")),
        "z_order": shape.get("z_order", shape.get("z_index")),
        "parent_id": shape.get("parent_id"),
        "fidelity": shape.get("fidelity", {}),
        "placeholder": shape.get("placeholder"),
        "is_group": shape.get("is_group", False),
        "children": shape.get("children", []),
    }
    return Component(
        type=_component_type(shape),
        id=shape.get("id"),
        x=geometry.get("left"),
        y=geometry.get("top"),
        w=geometry.get("width"),
        h=geometry.get("height"),
        text=_text_value(shape),
        data={
            "name": shape.get("name"),
            "source_type": shape.get("type"),
            "fidelity": fidelity,
        },
        style=style,
        provenance=[Provenance(source_id=source, locator=f"shape:{shape.get('id', '')}")],
    )


def template_dna_to_ir(dna: dict[str, Any], *, source: str | None = None) -> Presentation:
    """Convert Template DNA v0.3 into the project's Universal Presentation IR.

    This is deliberately loss-aware: the normalized fields feed the stable IR,
    while source-specific fidelity stays attached to each component.  It also
    preserves master/theme information at presentation level instead of flattening
    it into individual shapes.
    """
    source_id = source or str(dna.get("source") or "template-dna")
    presentation_info = dna.get("presentation") or {}
    slides: list[Slide] = []

    for index, raw_slide in enumerate(dna.get("slides") or [], 1):
        role = str(raw_slide.get("role") or "body")
        components = [
            _component(shape, source_id)
            for shape in (raw_slide.get("shapes") or [])
        ]
        purpose = _ROLE_TO_PURPOSE.get(role, "content")
        slides.append(
            Slide(
                id=str(raw_slide.get("slide") or index),
                purpose=purpose,
                layout=raw_slide.get("layout_name"),
                components=components,
            )
        )

    theme = {
        "template_dna_schema": dna.get("schema"),
        "slide_size_inches": presentation_info.get("slide_size_inches"),
        "theme": dna.get("theme", {}),
        "masters": dna.get("masters", []),
        "global_style_statistics": dna.get("global_style_statistics", {}),
        "special_surfaces": {
            "first": bool((dna.get("special_surfaces") or {}).get("first")),
            "last": bool((dna.get("special_surfaces") or {}).get("last")),
        },
    }
    return Presentation(
        version="0.1",
        title=str(dna.get("source") or "Imported presentation"),
        slides=slides,
        theme=theme,
        sources=[{"id": source_id, "kind": "pptx-template-dna"}],
    )
