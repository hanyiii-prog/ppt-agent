from __future__ import annotations

from collections import Counter
from typing import Any


def _records(slide: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    def walk(items: list[dict[str, Any]]) -> None:
        for shape in items:
            result.append(shape)
            walk(shape.get("children") or [])
    walk(slide.get("shapes") or [])
    return result


def extract_visual_grammar(dna: dict[str, Any]) -> dict[str, Any]:
    """Infer reusable visual rules without throwing away source-level DNA."""
    slides = dna.get("slides") or []
    role_counts = Counter(str(s.get("role", "body")) for s in slides)
    type_counts = Counter()
    signatures = Counter()
    for slide in slides:
        for shape in _records(slide):
            type_counts[str(shape.get("type", "unknown"))] += 1
        signature = slide.get("layout_signature")
        if signature is not None:
            signatures[str(signature)] += 1

    return {
        "roles": dict(role_counts),
        "element_type_frequency": dict(type_counts),
        "layout_signature_frequency": dict(signatures),
        "rules": {
            "first_slide_is_special_surface": bool(slides and slides[0].get("role") == "first"),
            "last_slide_is_special_surface": bool(slides and slides[-1].get("role") == "last"),
            "body_layout_reuse_detected": len(signatures) < max(1, len(slides) - 1),
        },
    }
