from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_layout_signature(shapes: list[dict[str, Any]]) -> str:
    records = []
    for shape in shapes:
        geometry = shape.get("geometry") or {}
        records.append({
            "type": shape.get("type"),
            "x": geometry.get("left"),
            "y": geometry.get("top"),
            "w": geometry.get("width"),
            "h": geometry.get("height"),
            "rotation": geometry.get("rotation"),
            "parent": shape.get("parent_id"),
            "z": shape.get("z_index", shape.get("z_order")),
        })
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
