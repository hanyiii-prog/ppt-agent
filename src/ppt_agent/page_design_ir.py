from __future__ import annotations

from typing import Any

from .page_family import select_page_family
from .slot_allocator import allocate_slots
from .slide_spec import SlideSpec

SCHEMA = "page-design-ir/v1"


def build_page_design_ir(
    outline: dict[str, Any] | Any,
    template: dict[str, Any],
    slide_specs: list[SlideSpec] | list[dict[str, Any]],
) -> dict[str, Any]:
    """Compile outline + SlideSpecs + template into a Page Design IR."""
    outline_slides = outline.slides if hasattr(outline, "slides") else outline.get("slides") or []
    lookup = {
        item["id"] if isinstance(item, dict) else item.id: item
        for item in slide_specs
    }
    pages: list[dict[str, Any]] = []
    for number, item in enumerate(outline_slides, 1):
        spec = lookup.get(item.get("id"))
        spec_dict = spec.to_dict() if isinstance(spec, SlideSpec) else dict(spec or {})
        spec_dict.setdefault("kind", item.get("kind"))
        spec_dict.setdefault("id", item.get("id"))
        spec_dict.setdefault("title", item.get("title"))
        family = select_page_family(template, spec_dict)
        slots = allocate_slots(family, spec_dict)
        pages.append({
            "page_no": number,
            "page_id": item.get("id"),
            "slide_spec_id": item.get("id"),
            "kind": item.get("kind"),
            "title": item.get("title"),
            "takeaway": item.get("takeaway") or "",
            "purpose": item.get("purpose") or "",
            "visual_form": item.get("visual_form") or "",
            "relations": item.get("relations") or [],
            "blocks": _blocks_from_spec(spec_dict),
            "template_family": family.get("id"),
            "composition": item.get("visual_form") or "text_evidence",
            "slots": slots,
            "speaker_notes": item.get("speaker_notes") or "",
            "warnings": [],
        })
    return {
        "schema": SCHEMA,
        "template_id": template.get("id"),
        "theme": template.get("theme") or {},
        "pages": pages,
    }


def _blocks_from_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    content = spec.get("content") or {}
    result: list[dict[str, Any]] = []
    if content.get("table"):
        result.append(content["table"])
    if content.get("items"):
        result.append({
            "id": f"{spec.get('id')}-items",
            "type": "bullets",
            "items": [item.get("text") for item in content["items"] if item.get("text")],
        })
    if content.get("lead"):
        result.append({
            "id": f"{spec.get('id')}-lead",
            "type": "paragraph",
            "text": content["lead"],
        })
    return result


__all__ = ["SCHEMA", "build_page_design_ir"]
