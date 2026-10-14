from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .source_pack import SourcePack

SCHEMA = "evidence-graph/v1"

_CONTRAST = re.compile(r"对比|对照|vs|versus|相比|however|but", re.IGNORECASE)
_SEQUENCE = re.compile(r"第[一二三四五六七八九十\d]+[步阶段]|step|phase|order|流程", re.IGNORECASE)
_PROGRESS = re.compile(r"完成|进行中|计划|complete|underway|planned", re.IGNORECASE)
_CAUSAL = re.compile(r"因为|由于|导致|因此|because|therefore|caused", re.IGNORECASE)
_OWNERSHIP = re.compile(r"负责|归属|owner|belongs", re.IGNORECASE)
_DISTRIBUTION = re.compile(r"占比|分布|percent|share|distribution", re.IGNORECASE)
_CORRELATION = re.compile(r"相关|关联|correlat", re.IGNORECASE)


@dataclass
class EvidenceGraph:
    schema: str
    facts: list[dict[str, Any]]
    entities: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_source_pack(cls, pack: SourcePack) -> "EvidenceGraph":
        facts: list[dict[str, Any]] = []
        block_facts: dict[str, str] = {}
        for index, block in enumerate(pack.blocks, 1):
            text = _block_payload_text(block)
            fact = {
                "id": f"fact-{index:04d}",
                "claim": text,
                "source_block_ids": [block["id"]],
                "fact_type": _fact_type(block),
                "confidence": 1.0 if block.get("type") == "table" else 0.85,
                "locked": True,
            }
            facts.append(fact)
            block_facts[block["id"]] = fact["id"]
            block["facts"] = [fact["id"]]

        relations = infer_relations(pack, block_facts)
        return cls(
            schema=SCHEMA,
            facts=facts,
            entities=_entities(pack),
            relations=relations,
            conflicts=_conflicts(facts),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_evidence_graph(pack: SourcePack) -> EvidenceGraph:
    return EvidenceGraph.from_source_pack(pack)


def infer_relations(pack: SourcePack, block_facts: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Infer content relations from block type and text, not page kind."""
    result: list[dict[str, Any]] = []
    index = 0
    facts = block_facts or {
        block["id"]: f"fact-{position:04d}"
        for position, block in enumerate(pack.blocks, 1)
    }
    while index < len(pack.blocks):
        block = pack.blocks[index]
        payload = _block_payload_text(block)
        if block.get("type") == "ordered":
            for position, item in enumerate(block.get("items") or [], 1):
                next_item = block["items"][position] if position < len(block["items"]) else None
                result.append({
                    "id": f"relation-{len(result) + 1:04d}",
                    "type": "sequence",
                    "from": facts.get(block["id"], ""),
                    "to": facts.get(block["id"], ""),
                    "source_block_ids": [block["id"]],
                    "label": item,
                    "order": position,
                })
            index += 1
            continue
        if _CONTRAST.search(payload):
            result.append({
                "id": f"relation-{len(result) + 1:04d}",
                "type": "contrast",
                "from": facts.get(block["id"], ""),
                "to": facts.get(block["id"], ""),
                "source_block_ids": [block["id"]],
            })
        elif _SEQUENCE.search(payload):
            result.append(_relation(facts, block, "sequence", result=result))
        elif _PROGRESS.search(payload):
            result.append(_relation(facts, block, "progress", result=result))
        elif _CAUSAL.search(payload):
            result.append(_relation(facts, block, "causal", result=result))
        elif _OWNERSHIP.search(payload):
            result.append(_relation(facts, block, "ownership", result=result))
        elif _DISTRIBUTION.search(payload):
            result.append(_relation(facts, block, "distribution", result=result))
        elif _CORRELATION.search(payload):
            result.append(_relation(facts, block, "correlation", result=result))
        if block.get("type") == "table":
            result.append(_relation(
                facts, block,
                "comparison" if len(block.get("headers") or []) == 2 else "matrix",
                result=result,
            ))
        elif block.get("type") == "heading":
            result.append(_relation(facts, block, "hierarchy", result=result))
        else:
            result.append(_relation(facts, block, "part_of", result=result))
        index += 1
    return result


def _relation(
    facts: dict[str, str],
    block: dict[str, Any],
    relation_type: str,
    *,
    result: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"relation-{len(result or []) + 1:04d}",
        "type": relation_type,
        "from": facts.get(block["id"], ""),
        "to": facts.get(block["id"], ""),
        "source_block_ids": [block["id"]],
    }


def _entities(pack: SourcePack) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in pack.blocks:
        payload = _block_payload_text(block)
        for candidate in re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b|[\u4e00-\u9fff]{2,6}(?:系统|模块|阶段|服务)", payload):
            if candidate in seen:
                continue
            seen.add(candidate)
            entities.append({
                "id": f"entity-{len(entities) + 1:04d}",
                "name": candidate,
                "source_block_ids": [block["id"]],
            })
    return entities


def _conflicts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    numeric: dict[str, list[dict[str, Any]]] = {}
    pattern = re.compile(r"(\d+(?:\.\d+)?)(%|人|天|万|亿)?")
    for fact in facts:
        matches = pattern.findall(fact["claim"])
        for value, unit in matches:
            key = f"{unit or 'plain'}"
            numeric.setdefault(key, []).append(fact)
    conflicts: list[dict[str, Any]] = []
    for unit, group in numeric.items():
        values = sorted({
            match
            for fact in group
            for match in pattern.findall(fact["claim"])
            for match in [match[0]]
        }, key=lambda item: float(item))
        if len(values) > 1:
            conflicts.append({
                "id": f"conflict-{len(conflicts) + 1:04d}",
                "type": "numeric_difference",
                "unit": unit,
                "values": values,
                "fact_ids": [item["id"] for item in group],
            })
    return conflicts


def _fact_type(block: dict[str, Any]) -> str:
    if block.get("type") == "table":
        return "structured"
    if block.get("type") in {"bullets", "ordered"}:
        return "list"
    if any(ch.isdigit() for ch in _block_payload_text(block)):
        return "metric"
    return "narrative"


def _block_payload_text(block: dict[str, Any]) -> str:
    if block.get("type") == "table":
        rows = [block.get("headers") or []] + [row for row in block.get("rows") or []]
        return " | ".join(" / ".join(str(cell) for cell in row) for row in rows if row)
    if block.get("items"):
        return "; ".join(str(item) for item in block["items"])
    return str(block.get("text") or "")


__all__ = ["EvidenceGraph", "SCHEMA", "build_evidence_graph", "infer_relations"]
