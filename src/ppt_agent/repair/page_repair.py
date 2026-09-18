"""Page repair: the page-level entry that routes problems to the right fixer."""

from __future__ import annotations

from typing import Any, Callable

from .component_repair import redistribute_gaps
from .element_repair import repair_element
from .layout_repair import repair_page_layout
from .locking import LockSet, filter_locked
from .problem_detection import Problem, collect_problems


def repair_page(
    boxes: list[dict[str, Any]],
    width_in: float,
    height_in: float,
    *,
    locks: LockSet | None = None,
    external: list[dict[str, Any]] | None = None,
    margin_in: float = 0.7,
) -> dict[str, Any]:
    """One page's repair pass: element-level fixes first, then page re-solve.

    Returns a report with before/after problem summaries, per-element actions
    and the locked-out list. The input box list is never mutated.
    """
    locks = locks or LockSet()
    working = [dict(box) for box in boxes]
    problems = collect_problems(working, width_in, height_in,
                                external=external, margin_in=margin_in)
    actionable, locked_out = filter_locked(problems, locks)

    actions: list[dict[str, Any]] = []
    for problem in actionable:
        if problem.target_kind != "element" or problem.code in ("overlap",):
            continue  # geometry pair problems go to the page re-solve below
        index = _primary_index(problem.target_id)
        if index is None or index >= len(working):
            continue
        new_box, action = repair_element(problem, working[index], page_height_in=height_in)
        working[index] = new_box
        actions.append({"signature": problem.signature, "action": action})

    problems_after_elements = collect_problems(working, width_in, height_in,
                                               external=external, margin_in=margin_in)
    still_geometry, _still_locked = filter_locked(problems_after_elements, locks)
    if any(problem.code in ("overlap", "out_of_bounds", "margin_breach", "min_gap")
           for problem in still_geometry):
        working, layout_report = repair_page_layout(
            problems_after_elements, working, width_in, height_in,
            locks=locks, margin_in=margin_in,
        )
        actions.append({"action": layout_report.get("action"), "via": "layout_solver"})

    problems_final = collect_problems(working, width_in, height_in,
                                      external=external, margin_in=margin_in)
    return {
        "boxes": working,
        "before": len(problems),
        "after": len(problems_final),
        "actions": actions,
        "locked_out": locked_out,
        "residual": [problem.signature for problem in problems_final],
    }


def _primary_index(target_id: str) -> int | None:
    for part in target_id.replace("+", " ").split():
        if part.isdigit():
            return int(part)
    return None


def repair_component_group(
    boxes: list[dict[str, Any]],
    *,
    top: float,
    bottom: float,
) -> Callable[[list[dict[str, Any]]], list[dict[str, Any]]]:
    """Bind a redistribution pass for one component group (cards etc.)."""
    def apply(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return redistribute_gaps(group, top=top, bottom=bottom)
    return apply
