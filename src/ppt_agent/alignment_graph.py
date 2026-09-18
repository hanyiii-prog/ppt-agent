"""Alignment graph: the invisible lines a template's content snaps to.

Why this exists
---------------
Templates feel tidy because their boxes share edges and centres. This module
clusters left edges / horizontal centres / right edges (and the vertical
triad top / middle / bottom) on a tolerance grid, then reports the dominant
lines per page kind. Layout (batch 3.D) snaps to them; repair (batch 3.E)
flags boxes that fall off them. Pure geometry from v0.4 records -- no LLM.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

SCHEMA = "alignment-graph/v1"

_DEFAULT_TOLERANCE = 0.06
_MIN_GROUP = 2


def _bbox(record: dict[str, Any]) -> tuple[float, float, float, float] | None:
    geometry = record.get("geometry") or {}
    left, top = geometry.get("left"), geometry.get("top")
    width, height = geometry.get("width"), geometry.get("height")
    if None in (left, top, width, height):
        return None
    return (float(left), float(top), float(width), float(height))


def _cluster(values: list[float], tolerance: float) -> list[dict[str, Any]]:
    """Group sorted values; a group survives only with >= 2 members."""
    if not values:
        return []
    ordered = sorted(values)
    groups: list[list[float]] = [[ordered[0]]]
    for value in ordered[1:]:
        if value - groups[-1][-1] <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [
        {"at_in": round(sum(group) / len(group), 3), "count": len(group)}
        for group in groups
        if len(group) >= _MIN_GROUP
    ]


def page_alignment(
    records: list[dict[str, Any]], *, tolerance: float = _DEFAULT_TOLERANCE
) -> dict[str, list[dict[str, Any]]]:
    boxes = [box for record in records if (box := _bbox(record))]
    lefts = [b[0] for b in boxes]
    rights = [b[0] + b[2] for b in boxes]
    centers = [b[0] + b[2] / 2 for b in boxes]
    tops = [b[1] for b in boxes]
    bottoms = [b[1] + b[3] for b in boxes]
    middles = [b[1] + b[3] / 2 for b in boxes]
    return {
        "left": _cluster(lefts, tolerance),
        "center_x": _cluster(centers, tolerance),
        "right": _cluster(rights, tolerance),
        "top": _cluster(tops, tolerance),
        "middle_y": _cluster(middles, tolerance),
        "bottom": _cluster(bottoms, tolerance),
    }


def build_alignment_graph(
    deck_dna: dict[str, Any], *, tolerance: float = _DEFAULT_TOLERANCE
) -> dict[str, Any]:
    """Per-page-kind alignment aggregation over a deck DNA dict."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for page in deck_dna.get("slides") or []:
        grouped.setdefault(str(page.get("kind")), []).extend(page.get("layers") or [])

    per_kind: dict[str, Any] = {}
    for kind, records in sorted(grouped.items()):
        axes = page_alignment(records, tolerance=tolerance)
        per_kind[kind] = {
            "axes": axes,
            "dominant": {
                axis: entries[0] if entries else None
                for axis, entries in axes.items()
            },
        }
    return {
        "schema": SCHEMA,
        "tolerance_in": tolerance,
        "per_kind": per_kind,
    }
