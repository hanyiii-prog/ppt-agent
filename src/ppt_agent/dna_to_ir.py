from __future__ import annotations

from typing import Any

from .ir import Component, Presentation, Provenance, Slide


_ROLE_TO_PURPOSE = {"first": "cover", "last": "closing", "body": "content"}


def _component_type(shape: dict[str, Any]) -> str:
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
    if isinstance(text, dict):
        for key in ("text", "plain_text", "value"):
            if isinstance(text.get(key), str):
                return text[key]
    return None


def _component(shape: dict[str, Any], source: str) -> Component:
    geometry = shape.get("geometry") or {}
    style = shape.get("style") or {}
    # Preserve source fidelity instead of flattening it away. This includes
    # alpha/transparency, z-order, parent/child relationships, placeholders,
    # and the raw OOXML fingerprint captured by Template DNA.
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
        data={"name": shape.get("name"), "source_type": shape.get("type"), "fidelity": fidelity},
        style=style,
        provenance=[Provenance(source_id=source, locator=f"shape:{shape.get('id', '')}")],
    )


def _copy_surface(surface: Any) -> Any:
    """Keep special surfaces loss-aware; do not collapse a slide into a bool."""
    return surface if surface is not None else None


def template_dna_to_ir(dna: dict[str, Any], *, source: str | None = None) -> Presentation:
    """Convert Template DNA v0.3 into Universal Presentation IR without losing fidelity."""
    source_id = source or str(dna.get("source") or "template-dna")
    presentation_info = dna.get("presentation") or {}
    slides: list[Slide] = []

    for index, raw_slide in enumerate(dna.get("slides") or [], 1):
        role = str(raw_slide.get("role") or "body")
        components = [_component(shape, source_id) for shape in (raw_slide.get("shapes") or [])]
        slides.append(
            Slide(
                id=str(raw_slide.get("slide") or index),
                purpose=_ROLE_TO_PURPOSE.get(role, "content"),
                layout=raw_slide.get("layout_name"),
                components=components,
                data={
                    "role": role,
                    "background": raw_slide.get("background"),
                    "inheritance": raw_slide.get("inheritance"),
                    "layout_signature": raw_slide.get("layout_signature"),
                    "raw_slide_xml": raw_slide.get("raw_slide_xml"),
                } if hasattr(Slide, "data") else None,
            )
        )

    theme = {
        "template_dna_schema": dna.get("schema"),
        "slide_size_inches": presentation_info.get("slide_size_inches"),
        "slide_count": presentation_info.get("slide_count"),
        "theme": dna.get("theme", {}),
        "masters": dna.get("masters", []),
        "global_style_statistics": dna.get("global_style_statistics", {}),
        "special_surfaces": {
            "first": _copy_surface((dna.get("special_surfaces") or {}).get("first")),
            "last": _copy_surface((dna.get("special_surfaces") or {}).get("last")),
            "body_slide_count": (dna.get("special_surfaces") or {}).get("body_slide_count", 0),
        },
    }
    return Presentation(
        version="0.1",
        title=str(dna.get("source") or "Imported presentation"),
        slides=slides,
        theme=theme,
        sources=[{"id": source_id, "kind": "pptx-template-dna"}],
    )
