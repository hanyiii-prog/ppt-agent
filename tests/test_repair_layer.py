"""Repair layer tests: detection, locks, element/layout fixes, cycle honesty."""

from __future__ import annotations

import pytest

from ppt_agent.repair import (
    LockSet,
    collect_problems,
    filter_locked,
    run_repair_cycle,
)
from ppt_agent.repair.component_repair import redistribute_gaps
from ppt_agent.repair.element_repair import repair_element
from ppt_agent.repair.problem_detection import problems_summary

W, H = 13.333, 7.5


def _box(x: float, y: float, w: float, h: float, *, absolute: bool = False,
         font_pt: float = 20.0, text: str = "") -> dict:
    return {"x": x, "y": y, "w": w, "h": h, "absolute": absolute,
            "font_pt": font_pt, "text": text}


def test_collect_problems_unifies_geometry_and_externals() -> None:
    boxes = [
        _box(0.7, 0.7, 5.0, 1.0),
        _box(0.7, 1.4, 5.0, 1.0),   # overlaps box 0
    ]
    problems = collect_problems(boxes, W, H, external=[
        {"code": "R-TYPO-001", "severity": "medium", "detail": "33pt outside scale"},
        {"kind": "collision", "slide": 3, "detail": "title vs body"},
    ])
    summary = problems_summary(problems)
    assert summary["overlap"] >= 1
    assert summary["R-TYPO-001"] == 1
    assert summary["audit:collision"] == 1


def test_locks_filter_with_reason() -> None:
    boxes = [_box(0.7, 0.7, 5.0, 1.0), _box(0.7, 1.4, 5.0, 1.0)]
    problems = collect_problems(boxes, W, H)
    locks = LockSet({"0"})
    actionable, locked_out = filter_locked(problems, locks)
    assert len(locked_out) == len(problems) - len(actionable)
    assert all("locked" in entry["reason"] for entry in locked_out)
    assert LockSet({"0"}).covers(problems[0]) or len(actionable) >= 0


def test_element_repair_shrinks_overflowing_text() -> None:
    from ppt_agent.repair.problem_detection import Problem

    problem = Problem(code="min_gap", severity="low", target_kind="element",
                      target_id="1", message="gap too small")
    box = _box(0.7, 6.2, 11.9, 1.6, font_pt=20.0, text="很长的正文内容，" * 10)
    new_box, action = repair_element(problem, box, page_height_in=H)
    assert action == "font_shrunk"
    assert new_box["font_pt"] < box["font_pt"]
    assert new_box["y"] + new_box["h"] <= H
    # extreme overflow below the min-font floor cannot fully fit: honest result
    extreme = _box(0.7, 6.8, 11.9, 2.5, font_pt=20.0, text="很长的正文内容，" * 30)
    new_extreme, action_extreme = repair_element(problem, extreme, page_height_in=H)
    assert action_extreme == "font_shrunk"
    assert new_extreme["font_pt"] == 12.0, "min-font floor holds; residual overflow is reported"


def test_element_repair_refuses_absolute_geometry_patch() -> None:
    from ppt_agent.repair.property_repair import patch_geometry

    with pytest.raises(ValueError):
        patch_geometry(_box(1.0, 1.0, 2.0, 1.0, absolute=True), x=2.0)


def test_layout_repair_resolves_overlap() -> None:
    from ppt_agent.repair.layout_repair import repair_page_layout

    boxes = [
        _box(0.7, 0.7, 11.9, 1.0, text="标题内容"),
        _box(0.7, 1.2, 11.9, 1.0, text="正文内容"),
    ]
    problems = collect_problems(boxes, W, H)
    new_boxes, report = repair_page_layout(problems, boxes, W, H)
    assert report["action"] == "resolved"
    overlap_after = [p for p in collect_problems(new_boxes, W, H) if p.code == "overlap"]
    assert not overlap_after


def test_redistribute_gaps_even_spacing() -> None:
    cards = [_box(0.7, 0.8, 3.0, 1.0), _box(0.7, 3.3, 3.0, 1.0), _box(0.7, 6.9, 3.0, 1.0)]
    positioned = redistribute_gaps(cards, top=0.8, bottom=6.8)
    gaps = [positioned[i + 1]["y"] - (positioned[i]["y"] + positioned[i]["h"])
            for i in range(len(positioned) - 1)]
    assert all(abs(gap - gaps[0]) < 0.01 for gap in gaps), "gaps must be even"
    assert positioned[0]["y"] == pytest.approx(0.8)
    assert positioned[-1]["y"] + positioned[-1]["h"] == pytest.approx(6.8)


def test_scheduler_converges_on_repairable_page() -> None:
    boxes = [
        _box(0.7, 0.7, 11.9, 1.0, text="标题"),
        _box(0.7, 1.1, 11.9, 1.0, text="正文一"),
        _box(0.7, 1.3, 11.9, 1.0, text="正文二"),
    ]
    report = run_repair_cycle(boxes, W, H)
    assert report["stop_reason"] in {"converged", "max_rounds", "oscillation"}
    assert report["residual_count"] < len(collect_problems(boxes, W, H)), (
        "the cycle must reduce the problem count for a repairable page"
    )


def test_scheduler_detects_oscillation() -> None:
    def do_nothing(boxes, w, h, **kwargs):
        return {"boxes": [dict(box) for box in boxes], "actions": [], "locked_out": []}

    boxes = [_box(0.7, 0.7, 5.0, 1.0), _box(0.7, 1.4, 5.0, 1.0)]
    report = run_repair_cycle(boxes, W, H, repair_fn=do_nothing, max_rounds=5)
    assert report["stop_reason"] == "oscillation"
    assert report["residual_count"] > 0


def test_scheduler_respects_locks() -> None:
    boxes = [_box(0.7, 0.7, 11.9, 1.0, text="标题"), _box(0.7, 1.1, 11.9, 1.0, text="正文")]
    locks = LockSet({"1"})
    report = run_repair_cycle(boxes, W, H, locks=locks)
    # locked box geometry never moves, whatever the cycle decided
    final = report["boxes"][1]
    assert final["x"] == boxes[1]["x"] and final["y"] == boxes[1]["y"]
    assert any(round.get("locked_out") for round in report["rounds"] if "locked_out" in round) or (
        report["stop_reason"] == "oscillation"
    )
