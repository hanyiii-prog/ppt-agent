"""Iterative repair loop tests: real PPTX, real repair, oscillation guard."""
from pathlib import Path

import pytest

from ppt_agent.fidelity_pipeline import (
    FidelityRepairExhausted,
    detect_oscillation,
    repair_deck,
    validate_deck_fidelity,
)
from ppt_agent.fidelity_gate import compare_decks

from tests.fidelity_fixtures import build_rich_pptx, mutate_pptx


def _mutate_multi(tmp_path: Path, mutations: list[str]) -> Path:
    """Chain several single-property mutations onto one candidate deck."""
    reference = build_rich_pptx(tmp_path / "ref.pptx")
    candidate = reference
    for index, mutation in enumerate(mutations):
        candidate = mutate_pptx(candidate, tmp_path / f"cand-{index}.pptx", mutation)
    return reference, candidate


def test_repair_loop_closes_structural_failures(tmp_path: Path):
    reference = build_rich_pptx(tmp_path / "ref.pptx")
    candidate = mutate_pptx(reference, tmp_path / "cand.pptx", "rotation_changed")
    candidate = mutate_pptx(candidate, tmp_path / "cand2.pptx", "crop_changed")
    candidate = mutate_pptx(candidate, tmp_path / "cand3.pptx", "zorder_changed")

    result = repair_deck(reference, candidate, tmp_path / "work", max_iterations=3)
    assert result["passed"] is True
    assert result["iterations"] >= 1
    assert not result["remaining_issues"]
    final = compare_decks(reference, result["candidate_final"])
    assert final["passed"]


def test_repair_loop_repairs_multiple_pages(tmp_path: Path):
    reference = build_rich_pptx(tmp_path / "ref.pptx")
    # mutate slide 3 twice: position + gradient angle
    candidate = mutate_pptx(reference, tmp_path / "c1.pptx", "geometry_changed")
    candidate = mutate_pptx(candidate, tmp_path / "c2.pptx", "gradient_changed")
    result = repair_deck(reference, candidate, tmp_path / "work", max_iterations=3)
    assert result["passed"] is True
    assert compare_decks(reference, result["candidate_final"])["passed"]


def test_repair_loop_exhausts_on_irreparable_issue(tmp_path: Path):
    reference = build_rich_pptx(tmp_path / "ref.pptx")
    candidate = mutate_pptx(reference, tmp_path / "cand.pptx", "media_changed")
    with pytest.raises(FidelityRepairExhausted) as excinfo:
        repair_deck(reference, candidate, tmp_path / "work", max_iterations=2)
    payload = excinfo.value.payload
    assert payload["passed"] is False
    assert payload["remaining_issues"], "exhaustion must carry remaining issues"
    assert payload["oscillation"] is None or payload["oscillation"]["detected"]


def test_detect_oscillation_flags_a_b_a_pattern():
    history = [
        {"iteration": 1, "applied": [{"path": "slide.shapes[id=2].geometry.x", "operation": "restore_geometry", "target": 100}]},
        {"iteration": 2, "applied": [{"path": "slide.shapes[id=2].geometry.x", "operation": "restore_geometry", "target": 200}]},
        {"iteration": 3, "applied": [{"path": "slide.shapes[id=2].geometry.x", "operation": "restore_geometry", "target": 100}]},
    ]
    report = detect_oscillation(history)
    assert report and report["kind"] == "repair_oscillation"
    assert report["pattern"] == [100, 200, 100]


def test_detect_oscillation_flags_stalled_repairs():
    history = [
        {"iteration": 1, "applied": [{"path": "slide.shapes[id=2].geometry.x", "operation": "restore_geometry", "target": 100}]},
        {"iteration": 2, "applied": [{"path": "slide.shapes[id=2].geometry.x", "operation": "restore_geometry", "target": 100}]},
    ]
    report = detect_oscillation(history)
    assert report and report["kind"] == "repair_oscillation"


def test_detect_oscillation_passes_converging_repairs():
    history = [
        {"iteration": 1, "applied": [{"path": "slide.shapes[id=2].geometry.x", "operation": "restore_geometry", "target": 100}]},
        {"iteration": 2, "applied": [{"path": "slide.shapes[id=2].geometry.y", "operation": "restore_geometry", "target": 200}]},
    ]
    assert detect_oscillation(history) is None


def test_loop_stops_and_reports_oscillation(tmp_path: Path, monkeypatch):
    from ppt_agent import fidelity_pipeline as pipeline

    reference = build_rich_pptx(tmp_path / "ref.pptx")
    candidate = mutate_pptx(reference, tmp_path / "cand.pptx", "rotation_changed")

    # a broken executor that flips rotation between two wrong values forever
    flip = {"state": False}

    def broken_execute(pptx_path, plan, output_path, *, slide_index=1):
        flip["state"] = not flip["state"]
        output_path = Path(output_path)
        output_path.write_bytes(Path(pptx_path).read_bytes())
        directive = plan["directives"][0]
        return {
            "applied": [{"path": directive["path"], "operation": directive["operation"]}],
            "skipped": [],
            "failed": [],
            "reorder_targets": {},
            "output": str(output_path),
            "schema": "x",
        }

    def broken_target(plan, applied):
        return flip["state"]

    monkeypatch.setattr(pipeline, "execute_repair_plan", broken_execute)
    monkeypatch.setattr(pipeline, "_target_for", broken_target)

    with pytest.raises(FidelityRepairExhausted) as excinfo:
        pipeline.repair_deck(reference, candidate, tmp_path / "work", max_iterations=4)
    payload = excinfo.value.payload
    assert payload["oscillation"], "ping-pong repair must be detected"


def test_single_pass_validate_keeps_renderer_states(tmp_path: Path, monkeypatch):
    reference = build_rich_pptx(tmp_path / "ref.pptx")
    candidate = mutate_pptx(reference, tmp_path / "cand.pptx", "rotation_changed")
    # structural failure must stay a failure with render requested but unavailable
    from ppt_agent.visual_regression import VisualGateUnavailable
    import ppt_agent.visual_regression as vr

    monkeypatch.setattr(vr, "preview_backend", lambda: None)
    result = validate_deck_fidelity(reference, candidate, tmp_path / "work")
    assert result["passed"] is False
    assert result["structural"]["passed"] is False
    assert result["visual"]["status"] == "unavailable"
