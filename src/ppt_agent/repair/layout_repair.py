"""Layout repair: whole-page geometry fixes through the batch 3.D solver."""

from __future__ import annotations

from typing import Any

from ..layout.layout_solver import solve
from .locking import LockSet
from .problem_detection import Problem


def repair_page_layout(
    problems: list[Problem],
    boxes: list[dict[str, Any]],
    width_in: float,
    height_in: float,
    *,
    locks: LockSet | None = None,
    margin_in: float = 0.7,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Re-solve the page when geometry problems exist.

    Locked elements are honoured by freezing them: the solver only ever moves
    non-absolute, unlocked flow boxes, so a locked box is marked absolute for
    the solve pass and restored afterwards. Returns (new_boxes, report).
    """
    locks = locks or LockSet()
    geometry_codes = {"overlap", "out_of_bounds", "margin_breach", "min_gap"}
    if not any(problem.code in geometry_codes for problem in problems):
        return boxes, {"action": "skipped", "reason": "no geometry problems"}

    work = []
    restore = {}
    for index, box in enumerate(boxes):
        spec = dict(box)
        if str(index) in locks and not box.get("absolute"):
            restore[index] = dict(box)
            spec["absolute"] = True  # frozen for this pass
        work.append(spec)

    solved_specs, solver_report = solve(
        [_to_layout_box(spec) for spec in work], width_in, height_in, margin_in=margin_in
    )
    new_boxes = []
    for index, spec in enumerate(solved_specs):
        entry = {
            "x": spec.x, "y": spec.y, "w": spec.w, "h": spec.h,
            "absolute": work[index].get("absolute", False),
            "font_pt": spec.font_pt,
        }
        if "text" in work[index]:
            entry["text"] = work[index]["text"]
        if index in restore:  # restore the locked box verbatim
            entry = {**restore[index]}
        new_boxes.append(entry)
    report = {**solver_report, "action": "resolved", "locked_count": len(restore)}
    return new_boxes, report


def _to_layout_box(spec: dict[str, Any]) -> Any:
    from ..styling import LayoutBox

    return LayoutBox(
        spec,  # component slot carries the dict itself: geometry is what matters
        float(spec.get("x") or 0.0),
        float(spec.get("y") or 0.0),
        float(spec.get("w") or 0.05),
        float(spec.get("h") or 0.05),
        float(spec.get("font_pt") or 20.0),
        bool(spec.get("absolute")),
    )
