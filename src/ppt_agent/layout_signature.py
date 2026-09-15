from __future__ import annotations

import hashlib
import json
from typing import Any


def _canonical_record(shape: dict[str, Any]) -> dict[str, Any]:
    geometry = shape.get("geometry") or {}
    return {
        "type": shape.get("type"),
        "x": geometry.get("left"),
        "y": geometry.get("top"),
        "w": geometry.get("width"),
        "h": geometry.get("height"),
        "rotation": geometry.get("rotation"),
        "parent": shape.get("parent_id"),
        "z": shape.get("z_index", shape.get("z_order")),
    }


def canonical_layout_signature(shapes: list[dict[str, Any]]) -> str:
    """Return a stable signature for a slide's structural layout.

    The signature intentionally ignores object ids/names and canonicalizes the
    element sequence so equivalent shape collections produce the same hash.
    Z-order and parent relationships remain part of the structure.
    """
    records = [_canonical_record(shape) for shape in shapes]
    records.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
