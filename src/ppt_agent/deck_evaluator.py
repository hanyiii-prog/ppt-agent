from __future__ import annotations

from typing import Any

from .evidence_graph import EvidenceGraph
from .ir import Presentation
from .source_pack import SourcePack


def evaluate_deck(
    presentation: Presentation,
    outline: dict[str, Any] | Any,
    pack: SourcePack,
    evidence: EvidenceGraph | dict[str, Any],
    artifacts: dict[str, Any],
    planning_mode: str = "rules",
    *,
    visual_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    facts = evidence.facts if isinstance(evidence, EvidenceGraph) else evidence.get("facts") or []
    outline_slides = outline.slides if hasattr(outline, "slides") else outline.get("slides") or []
    omissions = outline.omissions if hasattr(outline, "omissions") else outline.get("omissions") or []
    source_ids = {block["id"] for block in pack.blocks}
    used = {
        ref
        for slide in outline_slides
        for ref in (slide.get("source_block_ids") or [])
    } | {item.get("id") for item in omissions if item.get("id")}
    missing = sorted(source_ids - used)
    unknown = sorted(used - source_ids)

    content_pages = [slide for slide in outline_slides if slide.get("kind") == "content"]
    missing_takeaways = [
        slide.get("id") for slide in content_pages
        if not str(slide.get("takeaway") or "").strip()
    ]
    block_to_fact = {
        block_id: fact["id"]
        for fact in facts
        for block_id in fact.get("source_block_ids") or []
    }
    referenced_facts = [
        block_to_fact[ref]
        for slide in outline_slides
        for ref in slide.get("source_block_ids") or []
        if ref in block_to_fact
    ]

    empty_slides = [slide.id for slide in presentation.slides if not slide.components]
    empty_titles = [
        slide.id for slide in presentation.slides
        if not str(slide.claim or "").strip()
    ]
    page_total_ok = len(presentation.slides) == len(outline_slides)
    passed = (
        not missing
        and not unknown
        and not missing_takeaways
        and not empty_slides
        and not empty_titles
        and page_total_ok
    )

    visual = visual_report or {
        "model_review": "not_run",
        "deterministic_review": "not_run",
        "warning": "No rendered pages were supplied to this evaluation; semantic visual review was not executed.",
    }
    return {
        "schema": "quality-report/v3",
        "status": "passed" if passed else "failed",
        "content_quality": {
            "source_coverage": round((len(source_ids) - len(missing)) / max(1, len(source_ids)), 3),
            "missing_source_blocks": missing,
            "unknown_source_blocks": unknown,
            "missing_takeaways": missing_takeaways,
            "evidence_traceability": round(
                len(set(referenced_facts)) / max(1, len(evidence_ids(facts))), 3
            ),
        },
        "structural_quality": {
            "page_total": len(presentation.slides),
            "outline_page_total": len(outline_slides),
            "slides_match_outline": page_total_ok,
            "empty_slides": empty_slides,
            "empty_titles": empty_titles,
        },
        "visual_quality": visual,
        "planning_mode": planning_mode,
    }


def evidence_ids(facts: list[dict[str, Any]]) -> set[str]:
    return {str(fact.get("id")) for fact in facts if fact.get("id")}


__all__ = ["evaluate_deck"]
