from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

SCHEMA = "deck-brief/v1"


@dataclass
class DeckBrief:
    schema: str
    audience: dict[str, Any]
    objective: str
    context: str
    tone: list[str]
    page_budget: dict[str, int]
    must_include: list[str]
    must_not_invent: bool
    template_preference: str | None
    visual_constraints: list[str]
    source_priority: list[str] = None

    def __post_init__(self) -> None:
        if self.source_priority is None:
            self.source_priority = []

    @classmethod
    def from_task(cls, task: dict[str, Any], max_pages: int = 25) -> "DeckBrief":
        if not isinstance(task, dict):
            raise ValueError("task constraints must be an object")
        page_budget = task.get("page_budget") if isinstance(task.get("page_budget"), dict) else {}
        maximum = _positive_int(page_budget.get("max"), _positive_int(task.get("max_pages"), max_pages))
        minimum = _positive_int(page_budget.get("min"), 1)
        if minimum > maximum:
            raise ValueError("page_budget.min cannot exceed page_budget.max")
        return cls(
            schema=SCHEMA,
            audience={
                "name": str(task.get("audience") or "general audience"),
                "knowledge_level": str(task.get("knowledge_level") or "mixed"),
                "decision_power": str(task.get("decision_power") or "medium"),
            },
            objective=str(task.get("objective") or task.get("task") or "present the supplied material clearly"),
            context=str(task.get("context") or ""),
            tone=_string_list(task.get("tone")) or ["formal", "credible"],
            page_budget={"min": minimum, "max": maximum},
            must_include=_string_list(task.get("must_include")),
            must_not_invent=True,
            template_preference=_optional_text(task.get("template")),
            visual_constraints=_string_list(task.get("visual_constraints")),
            source_priority=_string_list(task.get("source_priority")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value > 0:
        return value
    return default


__all__ = ["DeckBrief", "SCHEMA"]
