"""The bounded repair cycle: detect -> fix -> re-detect, with honesty guards.

Stops when ANY of these holds (and reports which):
* the problem set is empty (converged);
* the problem signatures did not change after a round (oscillation -- the
  repair is not working, further rounds would be theatre);
* ``max_rounds`` is exhausted.

Mirrors fidelity_pipeline's oscillation discipline for the layout/IR route.
"""

from __future__ import annotations

from typing import Any, Callable

from .locking import LockSet
from .problem_detection import Problem, collect_problems


def run_repair_cycle(
    boxes: list[dict[str, Any]],
    width_in: float,
    height_in: float,
    *,
    repair_fn: Callable[..., dict[str, Any]] | None = None,
    locks: LockSet | None = None,
    external: list[dict[str, Any]] | None = None,
    max_rounds: int = 3,
    margin_in: float = 0.7,
) -> dict[str, Any]:
    """Run bounded repair rounds over one page's boxes.

    ``repair_fn`` defaults to ``page_repair.repair_page``; callers may inject
    their own (same signature) for alternative strategies. The input list is
    never mutated -- the report carries the final box list.
    """
    if repair_fn is None:
        from .page_repair import repair_page

        repair_fn = repair_page
    locks = locks or LockSet()

    working = [dict(box) for box in boxes]
    rounds: list[dict[str, Any]] = []
    stop_reason = "max_rounds"
    previous_signatures: set[str] | None = None

    for round_no in range(1, max_rounds + 1):
        problems: list[Problem] = collect_problems(
            working, width_in, height_in, external=external, margin_in=margin_in
        )
        signatures = {problem.signature for problem in problems}
        if not signatures:
            stop_reason = "converged"
            rounds.append({"round": round_no, "before": 0, "after": 0})
            break
        if previous_signatures is not None and signatures == previous_signatures:
            stop_reason = "oscillation"
            rounds.append({"round": round_no, "before": len(problems), "after": len(problems)})
            break
        previous_signatures = signatures

        report = repair_fn(
            working, width_in, height_in, locks=locks, external=external, margin_in=margin_in
        )
        working = [dict(box) for box in report["boxes"]]
        after = collect_problems(working, width_in, height_in,
                                 external=external, margin_in=margin_in)
        rounds.append({
            "round": round_no,
            "before": len(problems),
            "after": len(after),
            "actions": report.get("actions") or [],
            "locked_out": report.get("locked_out") or [],
        })

    final = collect_problems(working, width_in, height_in,
                             external=external, margin_in=margin_in)
    if final and stop_reason == "max_rounds":
        signatures_now = {problem.signature for problem in final}
        if signatures_now == previous_signatures:
            stop_reason = "oscillation"
    return {
        "boxes": working,
        "rounds": rounds,
        "stop_reason": stop_reason,
        "residual": [problem.signature for problem in final],
        "residual_count": len(final),
        "metadata": {"llm": "off", "scheduler": "rules/bounded"},
    }
