from __future__ import annotations

from typing import Any


def select_page_family(template: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Select a template page family from slide purpose and visual intent."""
    kind = str(spec.get("kind") or "content").lower()
    visual_forms = set(
        str(form).lower()
        for form in (spec.get("visual_intent") or {}).get("preferred_forms") or []
    )
    relations = set(str(item).lower() for item in spec.get("relations") or [])
    families = template.get("page_families") or []
    if kind in {"cover", "closing"}:
        for family in families:
            if family.get("id") == kind:
                return family

    for family in families:
        if not str(family.get("id", "")).startswith("content-"):
            continue
        forms = {str(item).lower() for item in family.get("visual_forms") or []}
        if visual_forms & forms:
            return family
    for family in families:
        if not str(family.get("id", "")).startswith("content-"):
            continue
        tags = {str(item).lower() for item in family.get("purpose_tags") or []}
        if relations & tags:
            return family
    for family in families:
        if str(family.get("id", "")).startswith("content-"):
            return family
    raise ValueError(f"template {template.get('id')!r} has no usable content page family")


__all__ = ["select_page_family"]
