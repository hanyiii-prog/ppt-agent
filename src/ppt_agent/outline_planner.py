from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .content_ir import ContentBlock, ContentDocument
from .deck_brief import DeckBrief
from .evidence_graph import EvidenceGraph
from .source_pack import SourcePack

SCHEMA = "outline/v1"


@dataclass
class Outline:
    schema: str
    title: str
    story: dict[str, Any]
    slides: list[dict[str, Any]]
    omissions: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    planning_mode: str = "rules"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def plan_outline(
    document: ContentDocument,
    pack: SourcePack,
    brief: DeckBrief,
    *,
    llm_fn: Callable[[str], str] | None = None,
) -> Outline:
    if llm_fn is None:
        return rule_outline(document, pack, brief)
    prompt = _prompt(document, pack, brief)
    try:
        response = llm_fn(prompt)
        outline = _model_outline(document, pack, brief, response)
    except Exception as exc:
        outline = rule_outline(document, pack, brief)
        outline.warnings.append(f"model outline failed: {type(exc).__name__}: {exc}")
        outline.planning_mode = "rules_fallback"
    return outline


def validate_outline_with_model(
    outline: Outline,
    pack: SourcePack,
    brief: DeckBrief,
    *,
    llm_fn: Callable[[str], str],
) -> dict[str, Any]:
    """Ask the model to review an already rule-validated outline."""
    prompt = json.dumps({
        "task": "Review this outline for repetition, weak purpose and missing evidence.",
        "brief": brief.to_dict(),
        "outline": outline.to_dict(),
        "source_blocks": [{"id": block["id"], "text": _block_text(block)} for block in pack.blocks],
    }, ensure_ascii=False, indent=2)
    try:
        payload = _json_payload(llm_fn(prompt))
    except Exception as exc:
        return {
            "schema": "outline-review/v1",
            "passed": True,
            "issues": [],
            "warning": f"model outline review failed: {type(exc).__name__}: {exc}",
        }
    issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
    return {
        "schema": "outline-review/v1",
        "passed": payload.get("passed") is not False,
        "issues": issues,
        "warning": None,
    }


def rule_outline(document: ContentDocument, pack: SourcePack, brief: DeckBrief) -> Outline:
    slides: list[dict[str, Any]] = [{
        "id": "slide-0001", "kind": "cover",
        "title": document.title or pack.title or "Presentation",
        "purpose": "establish topic and context", "takeaway": "",
        "source_block_ids": [], "evidence_ids": [], "visual_form": "cover",
        "relations": [], "speaker_notes": "", "layout_variant": "standard",
    }]
    index = 0
    blocks = document.blocks
    while index < len(blocks):
        block = blocks[index]
        group: list[ContentBlock] = []
        title = document.title or "Content"
        if block.type == "heading" and (block.level or 1) <= 2:
            title = block.text or title
            group = [block]
            index += 1
            while index < len(blocks):
                nxt = blocks[index]
                if nxt.type == "heading" and (nxt.level or 1) <= 2:
                    break
                group.append(nxt)
                index += 1
        else:
            while index < len(blocks):
                nxt = blocks[index]
                if nxt.type == "heading" and (nxt.level or 1) <= 2:
                    break
                group.append(nxt)
                index += 1
                if sum(_block_volume(item) for item in group) > 500:
                    break
        refs = [_original_id(item.id, pack) for item in group]
        slides.append({
            "id": f"slide-{len(slides) + 1:04d}", "kind": "content",
            "title": title, "purpose": f"explain {title}", "takeaway": _short_takeaway(group),
            "source_block_ids": refs, "evidence_ids": refs,
            "visual_form": _rule_visual_form(group), "relations": _rule_relations(group),
            "speaker_notes": "", "layout_variant": "standard",
        })
    slides.append({
        "id": f"slide-{len(slides) + 1:04d}", "kind": "closing", "title": "Thank you",
        "purpose": "close the presentation", "takeaway": "",
        "source_block_ids": [], "evidence_ids": [], "visual_form": "closing",
        "relations": [], "speaker_notes": "", "layout_variant": "standard",
    })
    slides = _respect_page_budget(slides, brief)
    return Outline(
        schema=SCHEMA, title=document.title or pack.title or "Presentation",
        story=_rule_story(brief), slides=slides, planning_mode="rules",
    )


def _model_outline(
    document: ContentDocument,
    pack: SourcePack,
    brief: DeckBrief,
    response: str,
) -> Outline:
    payload = _json_payload(response)
    if payload.get("schema") not in (None, SCHEMA, "storyboard/v1"):
        raise ValueError(f"unsupported outline schema {payload.get('schema')!r}")
    raw_slides = list(payload.get("slides") or [])
    if not raw_slides:
        raise ValueError("outline response has no slides")
    if raw_slides[0].get("kind") != "cover":
        raw_slides.insert(0, {"kind": "cover", "title": document.title or "Presentation"})
    if raw_slides[-1].get("kind") != "closing":
        if len(raw_slides) < brief.page_budget["max"]:
            raw_slides.append({"kind": "closing", "title": "Thank you"})
    slides: list[dict[str, Any]] = []
    for number, item in enumerate(raw_slides, 1):
        refs = list(item.get("source_block_ids") or item.get("source_blocks") or [])
        slides.append({
            "id": f"slide-{number:04d}", "kind": item.get("kind") or "content",
            "title": item.get("title") or f"Slide {number}",
            "purpose": item.get("purpose") or item.get("key_message") or "present evidence",
            "takeaway": item.get("takeaway") or item.get("key_message") or "",
            "source_block_ids": refs, "evidence_ids": refs,
            "visual_form": item.get("visual_form") or "", "relations": item.get("relations") or [],
            "speaker_notes": item.get("speaker_notes") or "", "layout_variant": item.get("layout_variant") or "standard",
        })
    return Outline(
        schema=SCHEMA, title=document.title or "Presentation",
        story=payload.get("story") or _rule_story(brief),
        slides=slides,
        omissions=payload.get("omissions") or payload.get("omitted_source_blocks") or [],
        warnings=payload.get("warnings") or [],
        planning_mode="model",
    )


def _rule_story(brief: DeckBrief) -> dict[str, str]:
    return {
        "opening_question": "Why does this matter now?",
        "central_thesis": brief.objective,
        "closing_action": "Agree on next steps",
    }


def _respect_page_budget(
    slides: list[dict[str, Any]],
    brief: DeckBrief,
) -> list[dict[str, Any]]:
    """Merge conservative content pages until a hard page budget is met."""
    maximum = int(brief.page_budget["max"])
    merged = list(slides)
    while len(merged) > maximum:
        content_indexes = [
            index for index, slide in enumerate(merged)
            if slide.get("kind") == "content"
        ]
        if len(content_indexes) < 2:
            break
        left_index = content_indexes[-2]
        right_index = content_indexes[-1]
        left, right = merged[left_index], merged[right_index]
        forms = {
            str(left.get("visual_form") or "text_evidence"),
            str(right.get("visual_form") or "text_evidence"),
        }
        visual_form = (
            "table_evidence" if "table_evidence" in forms
            else "progress_sequence" if "progress_sequence" in forms
            else "text_evidence"
        )
        merged[left_index] = {
            **left,
            "title": f"{left.get('title', '')} and {right.get('title', '')}".strip(" and"),
            "purpose": "explain combined evidence",
            "takeaway": "; ".join(item for item in (
                left.get("takeaway"), right.get("takeaway")
            ) if item),
            "source_block_ids": list(dict.fromkeys(
                (left.get("source_block_ids") or []) + (right.get("source_block_ids") or [])
            )),
            "evidence_ids": list(dict.fromkeys(
                (left.get("evidence_ids") or []) + (right.get("evidence_ids") or [])
            )),
            "visual_form": visual_form,
            "relations": list(dict.fromkeys(
                (left.get("relations") or []) + (right.get("relations") or [])
            )),
        }
        del merged[right_index]
    return merged


def _prompt(document: ContentDocument, pack: SourcePack, brief: DeckBrief) -> str:
    blocks = [
        {"id": block["id"], "type": block["type"], "text": _block_text(block)}
        for block in pack.blocks
    ]
    return json.dumps({
        "task": "Create a narrative outline. Use only supplied source blocks.",
        "document": {"title": document.title, "format": document.format},
        "brief": brief.to_dict(),
        "source_blocks": blocks,
    }, ensure_ascii=False, indent=2)


def _json_payload(text: str) -> dict[str, Any]:
    value = (text or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        value = fenced.group(1)
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError("outline response root must be a JSON object")
    return result


def _block_text(block: dict[str, Any]) -> str:
    if block.get("type") == "table":
        rows = [block.get("headers") or []] + list(block.get("rows") or [])
        return " | ".join(" / ".join(str(cell) for cell in row) for row in rows if row)
    if block.get("items"):
        return "; ".join(str(item) for item in block["items"])
    return str(block.get("text") or "")


def _block_volume(block: ContentBlock) -> int:
    if block.type == "table":
        return len(block.headers) + sum(len(row) for row in block.rows) * 12
    if block.type in {"bullets", "ordered"}:
        return sum(len(item) for item in block.items)
    return len(block.text or "")


def _short_takeaway(blocks: list[ContentBlock]) -> str:
    non_headings = [block for block in blocks if block.type != "heading"]
    if any(block.type in {"bullets", "ordered"} for block in blocks):
        return "Supporting points are summarised below"
    if any(block.type == "table" for block in blocks):
        return "Key items and current status are summarised below"
    for block in non_headings:
        text = _block_text({"type": block.type, "text": block.text, "items": block.items})
        if text:
            return text[:110] + ("..." if len(text) > 110 else "")
    return "No supporting content"


def _rule_visual_form(blocks: list[ContentBlock]) -> str:
    if any(block.type == "table" for block in blocks):
        return "table_evidence"
    if any(
        block.type in {"bullets", "ordered"} and any(ch.isdigit() for ch in item)
        for block in blocks for item in block.items
    ):
        return "progress_sequence"
    return "text_evidence"


def _rule_relations(blocks: list[ContentBlock]) -> list[str]:
    form = _rule_visual_form(blocks)
    if form == "progress_sequence":
        return ["sequence", "progress"]
    if form == "table_evidence":
        return ["comparison", "distribution"]
    return ["part_of"]


def _original_id(block_id: str, pack: SourcePack) -> str:
    for item in pack.blocks:
        if item["id"] == block_id:
            return item["id"]
        if item["id"].endswith(f"-{block_id}") or item["id"].split("-", 1)[-1] == block_id:
            return item["id"]
    return block_id


__all__ = ["Outline", "SCHEMA", "plan_outline", "rule_outline"]
