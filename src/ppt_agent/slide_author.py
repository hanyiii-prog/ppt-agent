from __future__ import annotations

import json
import re
from typing import Any, Callable

from .evidence_graph import EvidenceGraph
from .outline_planner import Outline
from .slide_spec import SlideSpec, slide_spec_from_outline
from .source_pack import SourcePack


def author_slide_specs(
    outline: Outline,
    pack: SourcePack,
    evidence: EvidenceGraph,
    *,
    llm_fn: Callable[[str], str] | None = None,
) -> list[SlideSpec]:
    lookup = {block["id"]: block for block in pack.blocks}
    fact_by_block = {
        block_id: fact["id"]
        for fact in evidence.facts
        for block_id in fact.get("source_block_ids") or []
    }
    specs: list[SlideSpec] = []
    for position, item in enumerate(outline.slides, 1):
        refs = [ref for ref in item.get("source_block_ids") or [] if ref in lookup]
        blocks = [lookup[ref] for ref in refs]
        content = {
            "lead": _lead(blocks),
            "items": _items(blocks),
            "metrics": _metrics(blocks),
            "table": next((block for block in blocks if block.get("type") == "table"), None),
            "chart": None,
            "diagram": None,
            "image_requests": [],
        }
        if llm_fn is not None:
            try:
                content = _model_content(
                    item, blocks, content, llm_fn, position, len(outline.slides)
                )
            except Exception as exc:
                content = {**content, "authoring_warning": (
                    f"model slide authoring failed ({type(exc).__name__}); "
                    "used deterministic extraction"
                )}
        spec = slide_spec_from_outline(item, content)
        if content.get("speaker_notes"):
            spec.speaker_notes = str(content["speaker_notes"])
        spec.evidence_ids = list(dict.fromkeys(
            fact_by_block.get(ref, str(ref)) for ref in refs
        ))
        specs.append(spec)
    return specs


def _model_content(
    outline_slide: dict[str, Any],
    blocks: list[dict[str, Any]],
    fallback: dict[str, Any],
    llm_fn: Callable[[str], str],
    position: int,
    total: int,
) -> dict[str, Any]:
    response = llm_fn(json.dumps({
        "task": "Write one SlideSpec. Rewrite for presentation, but never invent facts.",
        "slide": position,
        "slide_total": total,
        "outline_slide": outline_slide,
        "source_blocks": [
            {"id": block["id"], "type": block.get("type"), "payload": _payload(block)}
            for block in blocks
        ],
        "required_fields": ["lead", "items", "metrics", "visual_intent", "speaker_notes"],
    }, ensure_ascii=False, indent=2))
    payload = _json_object(response)
    if str(payload.get("id") or outline_slide.get("id")) != str(outline_slide.get("id")):
        raise ValueError("slide author response has the wrong slide id")
    content = dict(fallback)
    lead = payload.get("lead")
    if isinstance(lead, str) and lead.strip():
        content["lead"] = lead.strip()
    items = payload.get("items")
    if isinstance(items, list):
        normalized: list[dict[str, str]] = []
        for item in items:
            if isinstance(item, str) and item.strip():
                normalized.append({"text": item.strip()})
            elif isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
                normalized.append({"text": item["text"].strip()})
        content["items"] = normalized
    metrics = payload.get("metrics")
    if isinstance(metrics, list):
        normalized_metrics: list[dict[str, str]] = []
        for metric in metrics:
            if (
                isinstance(metric, dict)
                and isinstance(metric.get("label"), str) and metric["label"].strip()
                and isinstance(metric.get("value"), str) and metric["value"].strip()
            ):
                normalized_metrics.append({
                    "label": metric["label"].strip(),
                    "value": metric["value"].strip(),
                })
        content["metrics"] = normalized_metrics
    visual_intent = payload.get("visual_intent")
    if isinstance(visual_intent, dict):
        preferred = visual_intent.get("preferred_forms")
        avoid = visual_intent.get("avoid_forms")
        density = visual_intent.get("density")
        emphasis = visual_intent.get("emphasis")
        content["visual_intent"] = {
            "preferred_forms": [str(item) for item in preferred or [] if str(item).strip()],
            "avoid_forms": [str(item) for item in avoid or [] if str(item).strip()],
            "density": str(density or "standard"),
            "emphasis": [str(item) for item in emphasis or [] if str(item).strip()],
        }
    notes = payload.get("speaker_notes")
    if isinstance(notes, str) and notes.strip():
        content["speaker_notes"] = notes.strip()
    return content


def _lead(blocks: list[dict[str, Any]]) -> str:
    for block in blocks:
        if block.get("type") == "paragraph" and block.get("text"):
            return str(block["text"]).strip()
    return ""


def _items(blocks: list[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for block in blocks:
        if block.get("type") in {"bullets", "ordered"}:
            for item in block.get("items") or []:
                result.append({"text": str(item)})
    return result


def _metrics(blocks: list[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for block in blocks:
        if block.get("type") in {"bullets", "ordered"}:
            for item in block.get("items") or []:
                if any(ch.isdigit() for ch in item):
                    result.append({"label": str(item), "value": str(item)})
        elif block.get("type") == "paragraph" and any(ch.isdigit() for ch in str(block.get("text") or "")):
            result.append({"label": str(block.get("text")), "value": str(block.get("text"))})
    return result


def _payload(block: dict[str, Any]) -> Any:
    if block.get("type") == "table":
        return {"headers": block.get("headers") or [], "rows": block.get("rows") or []}
    if block.get("items"):
        return block.get("items") or []
    return block.get("text")


def _json_object(response: str) -> dict[str, Any]:
    value = (response or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        value = fenced.group(1)
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError("slide author response root must be a JSON object")
    return result


__all__ = ["author_slide_specs"]
