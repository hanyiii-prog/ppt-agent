"""Element repair: single-element fixes driven by one Problem."""

from __future__ import annotations

from typing import Any

from .problem_detection import Problem
from .property_repair import shrink_font_to_fit

BOTTOM_MARGIN_IN = 0.2


def repair_element(
    problem: Problem,
    box: dict[str, Any],
    *,
    page_height_in: float,
) -> tuple[dict[str, Any], str]:
    """Fix one element per its problem. Returns (new_box, action).

    ``action`` is one of ``unchanged`` / ``font_shrunk`` / ``clamped`` /
    ``skipped``. Only minimal, verifiable fixes live here.
    """
    if problem.code == "min_gap" or problem.code == "out_of_bounds":
        available = max(0.5, page_height_in - float(box.get("y") or 0.0) - BOTTOM_MARGIN_IN)
        new_box, changed = shrink_font_to_fit(box, available)
        if changed:
            return new_box, "font_shrunk"
        return box, "unchanged"
    if problem.code == "margin_breach":
        from ..layout.whitespace import enforce_margins

        clamped = enforce_margins([box], float(problem.payload.get("width_in") or 13.333),
                                  page_height_in)[0]
        if clamped != box:
            return clamped, "clamped"
        return box, "unchanged"
    return box, "skipped"
