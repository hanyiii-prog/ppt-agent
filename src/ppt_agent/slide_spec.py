from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA = "slide-spec/v1"


@dataclass
class SlideSpec:
    schema: str
    id: str
    purpose: str
    takeaway: str
    title: str
    content: dict[str, Any]
    relations: list[str]
    visual_intent: dict[str, Any]
    evidence_ids: list[str]
    source_block_ids: list[str]
    speaker_notes: str = ""
    layout_constraints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def slide_spec_from_outline(item: dict[str, Any], content: dict[str, Any]) -> SlideSpec:
    return SlideSpec(
        schema=SCHEMA,
        id=str(item["id"]),
        purpose=str(item.get("purpose") or ""),
        takeaway=str(item.get("takeaway") or ""),
        title=str(item.get("title") or ""),
        content=content,
        relations=list(item.get("relations") or []),
        visual_intent=content.get("visual_intent") or {
            "preferred_forms": [item.get("visual_form") or "text_evidence"],
            "avoid_forms": [],
            "density": "standard",
            "emphasis": ["takeaway"],
        },
        evidence_ids=list(item.get("evidence_ids") or []),
        source_block_ids=list(item.get("source_block_ids") or []),
        speaker_notes=str(item.get("speaker_notes") or ""),
        layout_constraints={
            "min_body_font_pt": 16,
            "max_major_items": 5,
            "allow_split": False,
        },
    )


__all__ = ["SlideSpec", "SCHEMA", "slide_spec_from_outline"]
