"""Whitespace: the breathing room a resolved page keeps."""

from __future__ import annotations

from typing import Any

from .constraint_engine import BoxLike, _rect, _overlap_amount

DEFAULT_MARGIN_IN = 0.7


def whitespace_ratio(
    boxes: list[BoxLike],
    width_in: float,
    height_in: float,
) -> float:
    """1 - (union of box areas) / slide area, via inclusion-exclusion.

    Pairwise intersections are subtracted; triple overlaps are rare on
    well-formed pages and accepted as an approximation (documented).
    """
    slide_area = max(width_in * height_in, 1e-6)
    total = 0.0
    for box in boxes:
        _x, _y, w, h = _rect(box)
        total += max(w, 0.0) * max(h, 0.0)
    for i, box_a in enumerate(boxes):
        for box_b in boxes[i + 1:]:
            total -= _overlap_amount(box_a, box_b)
    return round(max(0.0, min(1.0, 1.0 - total / slide_area)), 4)


def enforce_margins(
    boxes: list[BoxLike],
    width_in: float,
    height_in: float,
    *,
    margin_in: float = DEFAULT_MARGIN_IN,
) -> list[BoxLike]:
    """Clamp *flow* boxes back into the content margins (absolute untouched).

    Returns new dicts; the input list is never mutated.
    """
    clamped: list[BoxLike] = []
    for box in boxes:
        if box.get("absolute"):
            clamped.append(dict(box))
            continue
        x, y, w, h = _rect(box)
        new_w = min(w, width_in - 2 * margin_in)
        new_x = min(max(x, margin_in), max(margin_in, width_in - margin_in - new_w))
        new_h = min(h, height_in - 2 * margin_in)
        new_y = min(max(y, margin_in), max(margin_in, height_in - margin_in - new_h))
        clamped.append({**box, "x": round(new_x, 4), "y": round(new_y, 4),
                        "w": round(max(new_w, 0.05), 4), "h": round(max(new_h, 0.05), 4)})
    return clamped
