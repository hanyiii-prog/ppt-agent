"""Spacing graph: the gaps a template keeps between its content boxes.

Why this exists
---------------
"这份模板的呼吸感是多少" must be a number, not a feeling. The spacing graph
collects every horizontal gap (between vertically-overlapping neighbours) and
every vertical gap (between horizontally-overlapping neighbours), clusters
them on a 0.05-inch grid and surfaces the dominant values per page kind.

Layout (batch 3.D) will snap to these values; the repair layer will treat a
deviating gap as a finding. Pure geometry from v0.4 records -- no LLM.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

SCHEMA = "spacing-graph/v1"

_STEP = 0.05
_OVERLAP_RATIO = 0.30


def _bbox(record: dict[str, Any]) -> tuple[float, float, float, float] | None:
    geometry = record.get("geometry") or {}
    left, top = geometry.get("left"), geometry.get("top")
    width, height = geometry.get("width"), geometry.get("height")
    if None in (left, top, width, height):
        return None
    return (float(left), float(top), float(width), float(height))


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    low = max(a[0], b[0])
    high = min(a[1], b[1])
    if high <= low:
        return 0.0
    return (high - low) / max(min(a[1] - a[0], b[1] - b[0]), 1e-6)


def page_spacing(records: list[dict[str, Any]]) -> dict[str, Any]:
    """All gaps between content boxes on one page."""
    boxes = [box for record in records if (box := _bbox(record))]
    h_gaps: Counter[float] = Counter()
    v_gaps: Counter[float] = Counter()

    for i, (l1, t1, w1, h1) in enumerate(boxes):
        r1, b1 = l1 + w1, t1 + h1
        for l2, t2, w2, h2 in boxes[i + 1:]:
            r2, b2 = l2 + w2, t2 + h2
            if _overlap((t1, b1), (t2, b2)) >= _OVERLAP_RATIO:
                gap = l2 - r1 if l2 >= r1 else (l1 - r2 if l1 >= r2 else None)
                if gap is not None and gap > 0:
                    h_gaps[round(round(gap / _STEP) * _STEP, 4)] += 1
            if _overlap((l1, r1), (l2, r2)) >= _OVERLAP_RATIO:
                gap = t2 - b1 if t2 >= b1 else (t1 - b2 if t1 >= b2 else None)
                if gap is not None and gap > 0:
                    v_gaps[round(round(gap / _STEP) * _STEP, 4)] += 1

    def _dominant(counter: Counter[float]) -> list[dict[str, Any]]:
        return [
            {"gap_in": value, "count": count}
            for value, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
            if count >= 2
        ][:3]

    return {
        "boxes": len(boxes),
        "horizontal_gaps": sum(h_gaps.values()),
        "vertical_gaps": sum(v_gaps.values()),
        "dominant_horizontal": _dominant(h_gaps),
        "dominant_vertical": _dominant(v_gaps),
    }


def build_spacing_graph(deck_dna: dict[str, Any]) -> dict[str, Any]:
    """Per-page-kind spacing aggregation over a deck DNA dict."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for page in deck_dna.get("slides") or []:
        grouped.setdefault(str(page.get("kind")), []).extend(page.get("layers") or [])

    per_kind = {kind: page_spacing(records) for kind, records in sorted(grouped.items())}
    global_h: Counter[float] = Counter()
    global_v: Counter[float] = Counter()
    for spacing in per_kind.values():
        for entry in spacing["dominant_horizontal"]:
            global_h[entry["gap_in"]] += entry["count"]
        for entry in spacing["dominant_vertical"]:
            global_v[entry["gap_in"]] += entry["count"]
    return {
        "schema": SCHEMA,
        "per_kind": per_kind,
        "global_dominant": {
            "horizontal": [
                {"gap_in": value, "count": count}
                for value, count in sorted(global_h.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            ],
            "vertical": [
                {"gap_in": value, "count": count}
                for value, count in sorted(global_v.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            ],
        },
    }
