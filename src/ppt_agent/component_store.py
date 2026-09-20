"""Persistent component store: reusable multi-element controls.

Components are stored on disk (``~/.ppt-agent/components/``) as JSON files.
Each stores STRUCTURE and RELATIVE GEOMETRY only -- never absolute colours,
fonts or transparency. When a component is placed into a deck, its visual
properties are resolved from the current template's page-kind DNA via
``component_style.resolve_component_style``. This separation means the same
"4-card grid" component looks correct under any template.

A component file looks like::

    {
      "component_id": "cards-grid-4",
      "kind": "cards_grid",
      "slots": [
        {"role": "title",  "rel": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.15}},
        {"role": "card-0", "rel": {"x": 0.0, "y": 0.2, "w": 0.45, "h": 0.35}},
        ...
      ],
      "min_items": 4,
      "max_items": 4,
      "created": "2026-09-20T...",
      "usage_count": 3
    }

``rel`` values are fractions of the component's bounding box on the slide.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "component-store/v1"


def store_dir() -> Path:
    """The persistent component store directory (created on demand)."""
    root = Path.home() / ".ppt-agent" / "components"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        root = Path(tempfile.gettempdir()) / ".ppt-agent" / "components"
        root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_id(component_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", component_id).strip("-").lower()


def save_component(component: dict[str, Any]) -> Path:
    """Write one component to the store (upsert by component_id)."""
    cid = _safe_id(str(component.get("component_id") or "unnamed"))
    path = store_dir() / f"{cid}.json"
    payload = dict(component)
    payload["updated"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_component(component_id: str) -> dict[str, Any] | None:
    """Read one component from the store; None when absent."""
    cid = _safe_id(component_id)
    path = store_dir() / f"{cid}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_components() -> list[dict[str, Any]]:
    """Read every component in the store, sorted by kind then id."""
    results: list[dict[str, Any]] = []
    for path in sorted(store_dir().glob("*.json")):
        try:
            results.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    results.sort(key=lambda c: (str(c.get("kind") or ""), str(c.get("component_id") or "")))
    return results


def find_by_kind(kind: str, *, item_count: int | None = None) -> list[dict[str, Any]]:
    """Return stored components matching ``kind`` (and optionally item_count)."""
    matches: list[dict[str, Any]] = []
    for component in list_components():
        if str(component.get("kind") or "") != kind:
            continue
        if item_count is not None:
            lo = int(component.get("min_items") or 0)
            hi = int(component.get("max_items") or 999)
            if not (lo <= item_count <= hi):
                continue
        matches.append(component)
    return matches


def increment_usage(component_id: str) -> None:
    """Bump the usage counter after a component is placed into a deck."""
    component = load_component(component_id)
    if component is None:
        return
    component["usage_count"] = int(component.get("usage_count") or 0) + 1
    save_component(component)


def build_component_from_plan(
    kind: str, slots: list[dict[str, Any]], *, component_id: str = ""
) -> dict[str, Any]:
    """Create a new component from slot definitions (rel geometry + roles)."""
    if not component_id:
        component_id = f"{kind}-{len(slots)}"
    return {
        "schema": SCHEMA,
        "component_id": component_id,
        "kind": kind,
        "slots": slots,
        "min_items": len(slots),
        "max_items": len(slots),
        "created": datetime.now(timezone.utc).isoformat(),
        "usage_count": 0,
    }
