"""Persistent element store: token-saving single-element templates.

Why this exists
---------------
Every generation run draws text boxes, bullet lists, dividers, card frames
and titles. Without a store the agent regenerates them from scratch each
time -- wasting LLM tokens for identical or near-identical elements.

``element_store`` provides a fingerprint-based cache:

1. ``fingerprint_element()`` computes a stable hash from the element's
   structural features (kind, preset geometry, text pattern, relative size
   bucket) -- not its absolute position or colour.
2. ``lookup(fingerprint)`` returns a stored element (IR component dict) or
   None.
3. ``store(fingerprint, element)`` saves it for future reuse.
4. When the cache misses, the caller generates the element (rules first,
   LLM as a bounded fallback), then calls ``store()`` so the next run hits.

Storage path: ``~/.ppt-agent/elements/<fingerprint>.json``
Each file stores the IR component dict plus a usage counter and the
generating template's fingerprint (for provenance, not isolation -- elements
are meant to be shared across templates with DNA-driven re-styling).
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "element-store/v1"


def store_dir() -> Path:
    root = Path.home() / ".ppt-agent" / "elements"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        root = Path(tempfile.gettempdir()) / ".ppt-agent" / "elements"
        root.mkdir(parents=True, exist_ok=True)
    return root


def fingerprint_element(element: dict[str, Any]) -> str:
    """Stable structural hash for an element (never includes colour/position)."""
    parts: list[str] = []
    parts.append(str(element.get("type") or "?"))
    parts.append(str(element.get("preset") or element.get("prst_geom") or "none"))

    size = element.get("size") or element.get("geometry") or {}
    w = size.get("w") or size.get("width") or 0
    h = size.get("h") or size.get("height") or 0
    bucket_w = round(float(w) / 0.05) if w else 0
    bucket_h = round(float(h) / 0.05) if h else 0
    parts.append(f"{bucket_w}x{bucket_h}")

    text = element.get("text") or ""
    text_pattern = re.sub(r"[0-9]+", "#", text)[:80]
    parts.append(text_pattern)

    if element.get("items"):
        parts.append(f"items:{len(element['items'])}")
    if element.get("data"):
        parts.append(f"data:{'y' if element['data'] else 'n'}")

    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def lookup(fingerprint: str) -> dict[str, Any] | None:
    """Return the stored element for a fingerprint, or None."""
    path = store_dir() / f"{fingerprint}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def store(fingerprint: str, element: dict[str, Any], *, source_fingerprint: str = "") -> Path:
    """Save one element under its fingerprint (upsert)."""
    path = store_dir() / f"{fingerprint}.json"
    payload = {
        "schema": SCHEMA,
        "fingerprint": fingerprint,
        "element": element,
        "source_template_fingerprint": source_fingerprint,
        "created": datetime.now(timezone.utc).isoformat(),
        "usage_count": int((lookup(fingerprint) or {}).get("usage_count") or 0),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def increment_usage(fingerprint: str) -> None:
    """Bump the usage counter after a cache hit."""
    entry = lookup(fingerprint)
    if entry is None:
        return
    entry["usage_count"] = int(entry.get("usage_count") or 0) + 1
    store_dir().mkdir(parents=True, exist_ok=True)
    (store_dir() / f"{fingerprint}.json").write_text(
        json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def stats() -> dict[str, Any]:
    """Return store statistics: total elements, total usage, top reused."""
    entries: list[dict[str, Any]] = []
    for path in sorted(store_dir().glob("*.json")):
        try:
            entries.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    total_usage = sum(int(e.get("usage_count") or 0) for e in entries)
    top = sorted(entries, key=lambda e: -int(e.get("usage_count") or 0))[:5]
    return {
        "schema": SCHEMA,
        "total_elements": len(entries),
        "total_usage": total_usage,
        "top_reused": [
            {"fingerprint": e.get("fingerprint"), "usage_count": e.get("usage_count"),
             "type": (e.get("element") or {}).get("type")}
            for e in top
        ],
    }


def clear() -> int:
    """Remove every stored element; returns the count deleted."""
    count = 0
    for path in store_dir().glob("*.json"):
        path.unlink()
        count += 1
    return count
