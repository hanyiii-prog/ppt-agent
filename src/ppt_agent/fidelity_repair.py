"""Turn structural fidelity findings into deterministic repair directives.

This module deliberately does not mutate a PPTX. It translates the evidence
from ``fidelity_diff`` into actionable, ordered repair operations so a later
renderer/clone builder can apply them without reinterpreting the diff.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


_PRIORITY = {
    "page_kind": 0,
    "layer_order": 1,
    "inheritance": 2,
    "geometry": 3,
    "style": 4,
    "media": 5,
    "text": 6,
    "table": 7,
    "other": 8,
}


@dataclass(frozen=True)
class RepairDirective:
    path: str
    category: str
    operation: str
    reference: Any
    candidate: Any
    reason: str
    priority: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _operation(category: str, path: str) -> str:
    p = path.lower()
    if category == "page_kind":
        return "restore_page_kind"
    if category == "layer_order":
        return "restore_layer_order"
    if category == "inheritance":
        if "placeholder" in p:
            return "restore_placeholder_inheritance"
        return "restore_master_layout_inheritance"
    if category == "geometry":
        if "rotation" in p or "flip_" in p:
            return "restore_transform"
        return "restore_geometry"
    if category == "style":
        if any(k in p for k in ("alpha", "opacity", "transparency")):
            return "restore_alpha"
        if "gradient" in p:
            return "restore_gradient"
        return "restore_style"
    if category == "media":
        if any(k in p for k in ("crop", "source_rect")):
            return "restore_media_crop"
        return "restore_media_asset"
    if category == "text":
        return "restore_typography"
    if category == "table":
        return "restore_table_geometry"
    return "restore_property"


def plan_repairs(issues: Iterable[Any]) -> list[RepairDirective]:
    """Create stable repair directives from FidelityIssue-like objects.

    Directives are sorted by category priority and then path. Duplicate paths
    are retained only once, keeping repair plans deterministic across runs.
    """
    seen: set[tuple[str, str]] = set()
    planned: list[RepairDirective] = []
    for issue in issues:
        category = str(getattr(issue, "category", "other"))
        path = str(getattr(issue, "path", ""))
        key = (category, path)
        if key in seen:
            continue
        seen.add(key)
        priority = _PRIORITY.get(category, _PRIORITY["other"])
        planned.append(
            RepairDirective(
                path=path,
                category=category,
                operation=_operation(category, path),
                reference=getattr(issue, "reference", None),
                candidate=getattr(issue, "candidate", None),
                reason=str(getattr(issue, "message", "fidelity mismatch")),
                priority=priority,
            )
        )
    planned.sort(key=lambda item: (item.priority, item.path, item.operation))
    return planned


def plan_from_report(report: Any) -> list[RepairDirective]:
    """Build a repair plan from a ``FidelityReport`` or compatible object."""
    return plan_repairs(getattr(report, "issues", ()))


def repair_plan_dict(report: Any) -> dict[str, Any]:
    """Serialize a repair plan without coupling callers to dataclass internals."""
    directives = plan_from_report(report)
    return {
        "schema": "template-dna/fidelity-repair/v1",
        "issue_count": len(getattr(report, "issues", ())),
        "directive_count": len(directives),
        "directives": [directive.to_dict() for directive in directives],
    }


__all__ = ["RepairDirective", "plan_from_report", "plan_repairs", "repair_plan_dict"]
