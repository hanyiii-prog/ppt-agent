"""Orchestrate structural and rendered fidelity gates without hiding failures."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .fidelity_gate import compare_decks


def validate_deck_fidelity(
    reference: str | Path,
    candidate: str | Path,
    workspace: str | Path,
    *,
    tolerance: float = 0.0005,
    render: bool = True,
    threshold_ssim: float = 0.995,
    threshold_mae: float = 0.005,
    threshold_mismatch: float = 0.01,
) -> dict[str, Any]:
    """Run structural fidelity first, then optional rendered-page comparison.

    Structural failure is never masked by a visual pass. If rendering is
    requested but unavailable, the result is explicitly ``visual.status`` =
    ``unavailable`` rather than being reported as a pass.
    """
    structural = compare_decks(reference, candidate, tolerance=tolerance)
    result: dict[str, Any] = {
        "schema": "template-dna/fidelity-pipeline/v1",
        "passed": bool(structural["passed"]),
        "structural": structural,
        "visual": {"status": "skipped", "passed": None},
    }
    if not render:
        return result

    try:
        from .visual_regression import render_and_compare

        visual = render_and_compare(
            Path(reference),
            Path(candidate),
            Path(workspace),
            threshold_ssim=threshold_ssim,
            threshold_mae=threshold_mae,
            threshold_mismatch=threshold_mismatch,
        )
    except Exception as exc:
        result["visual"] = {
            "status": "unavailable",
            "passed": False,
            "error": str(exc),
        }
        result["passed"] = False
        return result

    visual_payload = visual.to_dict()
    visual_payload["status"] = "completed"
    result["visual"] = visual_payload
    result["passed"] = bool(structural["passed"] and visual.passed)
    return result


def assert_deck_fidelity_pipeline(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Raise unless both structural and requested visual gates pass."""
    result = validate_deck_fidelity(*args, **kwargs)
    if not result["passed"]:
        structural = result["structural"]
        visual = result["visual"]
        if not structural["passed"]:
            raise AssertionError("Fidelity pipeline failed structural gate")
        if visual.get("status") == "unavailable":
            raise AssertionError(f"Fidelity pipeline visual gate unavailable: {visual.get('error', '')}")
        raise AssertionError("Fidelity pipeline failed visual gate")
    return result


__all__ = ["assert_deck_fidelity_pipeline", "validate_deck_fidelity"]
