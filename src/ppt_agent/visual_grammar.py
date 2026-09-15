from __future__ import annotations

from collections import Counter
from typing import Any

from .layout_signature import canonical_layout_signature


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
    signature_slides: dict[str, list[int]] = {}

    for slide in slides:
        records = _records(slide)
        for shape in records:
            type_counts[str(shape.get("type", "unknown"))] += 1

        supplied = slide.get("layout_signature")
        signature = str(supplied) if supplied is not None else canonical_layout_signature(records)
        signatures[signature] += 1
        number = slide.get("slide")
        if number is not None:
            signature_slides.setdefault(signature, []).append(int(number))

    repeated_signatures = {
        signature: numbers
        for signature, numbers in signature_slides.items()
        if len(numbers) > 1
    }

    return {
        "roles": dict(role_counts),
        "element_type_frequency": dict(type_counts),
        "layout_signature_frequency": dict(signatures),
        "reusable_layouts": repeated_signatures,
        "rules": {
            "first_slide_is_special_surface": bool(slides and slides[0].get("role") == "first"),
            "last_slide_is_special_surface": bool(slides and slides[-1].get("role") == "last"),
            "body_layout_reuse_detected": bool(repeated_signatures),
        },
    }
