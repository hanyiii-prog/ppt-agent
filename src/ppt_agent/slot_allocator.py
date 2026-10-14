from __future__ import annotations

from typing import Any


def allocate_slots(family: dict[str, Any], spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map slide content into declared template slots; never invent geometry."""
    allocated: dict[str, dict[str, Any]] = {}
    content = spec.get("content") or {}
    for slot in family.get("slots") or []:
        slot_id = str(slot.get("id") or "")
        if str(slot.get("kind") or "").lower() == "rect":
            allocated[slot_id] = {**slot, "value": ""}
            continue
        value = _slot_value(slot_id, content, spec)
        if value is None:
            continue
        allocated[slot_id] = {**slot, "value": value}
    return allocated


def _slot_value(
    slot_id: str,
    content: dict[str, Any],
    spec: dict[str, Any],
) -> Any:
    if slot_id in {"title", "meta", "subtitle", "left_label", "right_label"}:
        if slot_id == "title":
            return spec.get("title")
        if slot_id == "subtitle":
            return content.get("lead")
        if slot_id in {"left_label", "right_label"}:
            return "Current state" if slot_id.startswith("left") else "Target state"
        return spec.get("takeaway")
    if slot_id == "body":
        items = content.get("items") or []
        if items:
            return "\n".join(f"• {item.get('text', '')}".rstrip() for item in items)
        return content.get("lead")
    if slot_id == "table":
        return content.get("table")
    return None


__all__ = ["allocate_slots"]
