"""Constraint engine: the violations a resolved page must not carry.

Operates on *box-like dicts* (``{"x","y","w","h","absolute",...}``) so both
the solver and the repair layer (batch 3.E) share one checker. Absolute
(template-injected) boxes are measured but never treated as violations by
themselves -- they are the template's own decisions.

Checks
------
``out_of_bounds``   box leaves the slide
``margin_breach``   a *flow* box crosses the content margins
``overlap``         two flow boxes overlap
``min_gap``         vertical gap between consecutive flow boxes too small
"""

from __future__ import annotations

from typing import Any

BoxLike = dict[str, Any]

DEFAULT_MARGIN_IN = 0.7
DEFAULT_MIN_GAP_IN = 0.08


def _rect(box: BoxLike) -> tuple[float, float, float, float]:
    return (
        float(box.get("x") or 0.0),
        float(box.get("y") or 0.0),
        float(box.get("w") or 0.0),
        float(box.get("h") or 0.0),
    )


def _overlap_amount(a: BoxLike, b: BoxLike) -> float:
    ax, ay, aw, ah = _rect(a)
    bx, by, bw, bh = _rect(b)
    overlap_w = min(ax + aw, bx + bw) - max(ax, bx)
    overlap_h = min(ay + ah, by + bh) - max(ay, by)
    if overlap_w <= 0 or overlap_h <= 0:
        return 0.0
    return round(overlap_w * overlap_h, 4)


def check_constraints(
    boxes: list[BoxLike],
    width_in: float,
    height_in: float,
    *,
    margin_in: float = DEFAULT_MARGIN_IN,
    min_gap_in: float = DEFAULT_MIN_GAP_IN,
) -> list[dict[str, Any]]:
    """Every violation of the page constraints, with explicit detail."""
    violations: list[dict[str, Any]] = []
    flow_boxes = [(index, box) for index, box in enumerate(boxes) if not box.get("absolute")]

    for index, box in enumerate(boxes):
        x, y, w, h = _rect(box)
        if x < -0.01 or y < -0.01 or x + w > width_in + 0.01 or y + h > height_in + 0.01:
            violations.append({
                "kind": "out_of_bounds",
                "index": index,
                "detail": f"box ({x:.2f},{y:.2f},{w:.2f}x{h:.2f}) leaves slide {width_in:.2f}x{height_in:.2f}",
            })

    for index, box in flow_boxes:
        x, y, w, h = _rect(box)
        if x < margin_in - 0.01 or x + w > width_in - margin_in + 0.01:
            violations.append({
                "kind": "margin_breach",
                "index": index,
                "detail": f"flow box crosses the {margin_in:.2f}in content margin",
            })

    for position, (index_a, box_a) in enumerate(flow_boxes):
        for index_b, box_b in flow_boxes[position + 1:]:
            amount = _overlap_amount(box_a, box_b)
            if amount > 0.01:
                violations.append({
                    "kind": "overlap",
                    "index": index_a,
                    "other": index_b,
                    "detail": f"flow boxes overlap by {amount} sq in",
                })

    ordered = sorted(flow_boxes, key=lambda pair: float(pair[1].get("y") or 0.0))
    for (index_a, box_a), (index_b, box_b) in zip(ordered, ordered[1:]):
        ax, ay, aw, ah = _rect(box_a)
        bx, by, _bw, _bh = _rect(box_b)
        gap = by - (ay + ah)
        if gap < min_gap_in - 0.005:
            violations.append({
                "kind": "min_gap",
                "index": index_a,
                "other": index_b,
                "detail": f"vertical gap {gap:.3f}in < {min_gap_in:.3f}in",
            })
    return violations


def violations_summary(violations: list[dict[str, Any]]) -> dict[str, int]:
    """Count violations by kind (deterministic order)."""
    summary: dict[str, int] = {}
    for violation in violations:
        summary[violation["kind"]] = summary.get(violation["kind"], 0) + 1
    return dict(sorted(summary.items()))
