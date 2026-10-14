from __future__ import annotations

from typing import Any

from .deck_brief import DeckBrief
from .source_pack import SourcePack


def validate_outline(
    outline: Any,
    pack: SourcePack,
    brief: DeckBrief,
    *,
    evidence: dict[str, Any] | None = None,
) -> list[str]:
    """Return a list of hard errors; empty means the outline is usable."""
    slides = outline.slides if hasattr(outline, "slides") else outline.get("slides") or []
    omissions = outline.omissions if hasattr(outline, "omissions") else outline.get("omissions") or []
    source_ids = {block["id"] for block in pack.blocks}
    evidence_dict = evidence.to_dict() if hasattr(evidence, "to_dict") else evidence or {}
    fact_ids = {
        item.get("id") for item in evidence_dict.get("facts") or []
    }
    used = {
        ref
        for slide in slides
        for ref in (slide.get("source_block_ids") or [])
    } | {item.get("id") for item in omissions if item.get("id")}
    unknown = sorted(used - source_ids)
    errors: list[str] = []
    if unknown:
        errors.append(f"outline references unknown source blocks: {unknown}")
    if len(slides) > brief.page_budget["max"]:
        errors.append(
            f"outline has {len(slides)} pages, exceeding max {brief.page_budget['max']}"
        )
    if len(slides) < brief.page_budget["min"]:
        errors.append(
            f"outline has only {len(slides)} pages, below min {brief.page_budget['min']}"
        )
    for slide in slides:
        if not slide.get("purpose"):
            errors.append(f"outline slide {slide.get('id')} has no purpose")
        if slide.get("kind") == "content" and not str(slide.get("takeaway") or "").strip():
            errors.append(f"outline content slide {slide.get('id')} has no takeaway")
        unknown_evidence = sorted(
            str(item) for item in slide.get("evidence_ids") or []
            if evidence is not None and item not in fact_ids
        )
        if unknown_evidence:
            errors.append(
                f"outline slide {slide.get('id')} references unknown evidence: {unknown_evidence}"
            )
    return errors


__all__ = ["validate_outline"]
