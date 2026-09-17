"""Fidelity pipeline 2.0: iterative repair loop with oscillation detection.

Closes the loop the plan requires::

    Pass 1 → Structural Diff → Repair → Pass 2 → Structural Diff →
    Render → Visual Diff → (Repair) → Pass 3 → Final Gate

with ``max_iterations`` (default 3), a full ``repair_history``, oscillation
detection (``A → B → A`` on the same property, or repeated no-progress
repairs of the same directive) and an explicit ``FidelityRepairExhausted``
failure that carries the remaining issues. Renderer unavailability and
renderer errors are preserved as their own states and never count as passes.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .fidelity_gate import compare_decks
from .fidelity_repair_executor import execute_repair_plan

LOOP_SCHEMA = "template-dna/fidelity-repair-loop/v1"


class FidelityRepairExhausted(RuntimeError):
    """Raised when the repair loop hits ``max_iterations`` with issues left."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(
            f"fidelity repair exhausted after {payload.get('iterations', 0)} iterations; "
            f"{len(payload.get('remaining_issues', []))} issue(s) remain"
        )
        self.payload = payload
        self.remaining = payload.get("remaining_issues", [])


# --------------------------------------------------------------------------- #
# oscillation detection
# --------------------------------------------------------------------------- #
def detect_oscillation(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Detect ``A → B → A`` value ping-pong or stalled repeated repairs.

    ``history`` is the list of iteration records; each carries the applied
    directives with their target (reference) values. Returns a report when the
    same property is being repaired back and forth, or repaired repeatedly
    without the issue ever disappearing.
    """
    sequences: dict[tuple[str, str], list[tuple[int, Any]]] = {}
    for record in history:
        iteration = int(record.get("iteration", 0))
        for directive in record.get("applied", []):
            key = (str(directive.get("path")), str(directive.get("operation")))
            sequences.setdefault(key, []).append((iteration, directive.get("target")))

    for (path, operation), values in sorted(sequences.items()):
        if len(values) < 3:
            continue
        tail = [value for _, value in values[-3:]]
        if tail[0] == tail[2] and tail[0] != tail[1]:
            return {
                "detected": True,
                "kind": "repair_oscillation",
                "path": path,
                "operation": operation,
                "pattern": tail,
            }
        if len(values) >= 3 and all(value == values[0][1] for _, value in values):
            return {
                "detected": True,
                "kind": "repair_oscillation",
                "path": path,
                "operation": operation,
                "pattern": [value for _, value in values],
                "note": "same target repaired repeatedly without converging",
            }
    # repeated identical repairs (stalled) with only two samples
    for (path, operation), values in sorted(sequences.items()):
        if len(values) >= 2 and all(value == values[0][1] for _, value in values) and len({i for i, _ in values}) == len(values):
            return {
                "detected": True,
                "kind": "repair_oscillation",
                "path": path,
                "operation": operation,
                "pattern": [value for _, value in values],
                "note": "same target repaired repeatedly without converging",
            }
    return None


# --------------------------------------------------------------------------- #
# repair loop
# --------------------------------------------------------------------------- #
def repair_deck(
    reference: str | Path,
    candidate: str | Path,
    workspace: str | Path,
    *,
    max_iterations: int = 3,
    render: bool = False,
    tolerance: float = 0.0005,
    threshold_ssim: float = 0.995,
    threshold_mae: float = 0.005,
    threshold_mismatch: float = 0.01,
) -> dict[str, Any]:
    """Iteratively repair a candidate deck against a reference deck.

    The source candidate is never mutated; every iteration writes a new
    package into ``workspace``. Structural failures are repaired page by page
    with the Repair Executor; when the structure passes, an optional render +
    visual diff closes the loop. Raises :class:`FidelityRepairExhausted` when
    iterations run out with issues remaining.
    """
    reference = Path(reference)
    candidate = Path(candidate)
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    current = workspace / "candidate-iter0.pptx"
    shutil.copy(candidate, current)

    history: list[dict[str, Any]] = []
    structural: dict[str, Any] | None = None
    visual: dict[str, Any] | None = None
    oscillation: dict[str, Any] | None = None

    for iteration in range(1, max_iterations + 1):
        structural = compare_decks(reference, current, tolerance=tolerance)
        record: dict[str, Any] = {"iteration": iteration, "phase": "structural", "applied": []}
        history.append(record)

        if structural["passed"]:
            if not render:
                return _payload(True, iteration, history, structural, visual, current, oscillation)
            from .visual_regression import visual_status

            visual = visual_status(
                reference,
                current,
                workspace / f"visual-iter{iteration}",
                threshold_ssim=threshold_ssim,
                threshold_mae=threshold_mae,
                threshold_mismatch=threshold_mismatch,
            )
            record["phase"] = "visual"
            record["visual_status"] = visual["status"]
            if visual["status"] == "visual_pass":
                return _payload(True, iteration, history, structural, visual, current, oscillation)
            # visual_fail cannot be mapped to property-level repairs once the
            # structure already matches; report honestly instead of faking one
            break

        any_applied = False
        for page in structural["pages"]:
            if page["passed"]:
                continue
            plan = page.get("repair_plan") or {"directives": []}
            next_path = workspace / f"candidate-iter{iteration}-page{page['slide_index']}.pptx"
            result = execute_repair_plan(current, plan, next_path, slide_index=page["slide_index"])
            current = next_path
            for directive in result["applied"]:
                record["applied"].append({
                    "path": directive["path"],
                    "operation": directive["operation"],
                    "target": _target_for(plan, directive),
                })
                any_applied = True
            record.setdefault("skipped", 0)
            record["skipped"] += len(result["skipped"])
            record.setdefault("failed", 0)
            record["failed"] += len(result["failed"])

        oscillation = detect_oscillation(history)
        if oscillation:
            break
        if not any_applied:
            break

    final_structural = compare_decks(reference, current, tolerance=tolerance)
    structural = final_structural
    payload = _payload(False, len(history), history, structural, visual, current, oscillation)
    raise FidelityRepairExhausted(payload)


def _target_for(plan: dict[str, Any], applied: dict[str, Any]) -> Any:
    for directive in plan.get("directives", []):
        if directive.get("path") == applied.get("path") and directive.get("operation") == applied.get("operation"):
            return directive.get("reference")
    return None


def _payload(
    passed: bool,
    iterations: int,
    history: list[dict[str, Any]],
    structural: dict[str, Any] | None,
    visual: dict[str, Any] | None,
    current: Path,
    oscillation: dict[str, Any] | None,
) -> dict[str, Any]:
    remaining = []
    if structural and not structural["passed"]:
        for page in structural["pages"]:
            for issue in page.get("issues", []):
                remaining.append({"slide_index": page["slide_index"], **issue})
        remaining.extend({"scope": "package", **issue} for issue in structural.get("package_issues", []))
    if visual and not visual.get("passed", False):
        remaining.append({"scope": "visual", "status": visual.get("status"), "error": visual.get("error")})
    return {
        "schema": LOOP_SCHEMA,
        "passed": passed,
        "iterations": iterations,
        "history": history,
        "structural": structural,
        "visual": visual,
        "remaining_issues": remaining,
        "oscillation": oscillation,
        "candidate_final": str(current),
    }


# --------------------------------------------------------------------------- #
# single-pass gates (kept for compatibility)
# --------------------------------------------------------------------------- #
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

    Structural failure is never masked by a visual pass. A missing renderer is
    explicitly reported as ``unavailable``; an installed renderer that fails
    during conversion is reported as ``error`` so infrastructure defects are
    not silently downgraded to a capability warning.
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
        from .visual_regression import VisualGateUnavailable
        unavailable = isinstance(exc, VisualGateUnavailable)
        result["visual"] = {
            "status": "unavailable" if unavailable else "error",
            "passed": False,
            "error": str(exc),
        }
        result["passed"] = False
        return result

    visual_payload = visual.to_dict()
    visual_payload["status"] = "completed" if visual.passed else "visual_fail"
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
        if visual.get("status") == "error":
            raise AssertionError(f"Fidelity pipeline visual gate error: {visual.get('error', '')}")
        raise AssertionError("Fidelity pipeline failed visual gate")
    return result


__all__ = [
    "FidelityRepairExhausted",
    "assert_deck_fidelity_pipeline",
    "detect_oscillation",
    "repair_deck",
    "validate_deck_fidelity",
]
