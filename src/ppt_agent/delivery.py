from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .page_validation import DeckGateReport, validate_rendered_pages
from .visual_regression import VisualReport, render_and_compare, render_pptx


@dataclass(frozen=True)
class DeliveryPolicy:
    """Hard release policy: one failed page blocks the whole deck."""

    max_repair_iterations: int = 3
    blank_threshold: float = 0.995
    visual_ssim: float = 0.995
    visual_mae: float = 0.005
    visual_mismatch: float = 0.01


@dataclass
class DeliveryAttempt:
    iteration: int
    pptx: str
    page_gate_passed: bool
    visual_gate_passed: bool | None
    failed_pages: list[int] = field(default_factory=list)
    repair_requests: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DeliveryReport:
    passed: bool
    iterations: int
    final_pptx: str
    attempts: list[DeliveryAttempt]
    page_gate: dict[str, Any] | None = None
    visual_gate: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _repair_requests(page_gate: DeckGateReport, visual_gate: VisualReport | None) -> list[dict[str, Any]]:
    """Convert deterministic failures into machine-readable repair tasks."""
    requests: list[dict[str, Any]] = []
    for page in page_gate.pages:
        if page.passed:
            continue
        requests.append({
            "page": page.page,
            "kind": "page_gate",
            "issues": list(page.issues),
            "actions": ["inspect source/IR", "repair layout or content", "rebuild page", "rerender page"],
        })
    if visual_gate:
        for page in visual_gate.pages:
            if page.passed:
                continue
            requests.append({
                "page": page.page,
                "kind": "visual_regression",
                "metrics": {
                    "ssim": page.ssim,
                    "mae": page.mae,
                    "mismatch_ratio": page.mismatch_ratio,
                },
                "actions": ["inspect diff image", "repair source/IR/rule", "rebuild page", "rerender page"],
            })
    return requests


def validate_delivery(
    pptx: Path,
    workspace: Path,
    *,
    reference_pptx: Path | None = None,
    policy: DeliveryPolicy | None = None,
) -> tuple[DeckGateReport, VisualReport | None]:
    """Run the complete production gate over the actual candidate deck."""
    policy = policy or DeliveryPolicy()
    rendered = render_pptx(pptx, workspace / "rendered")
    page_gate = validate_rendered_pages(pptx, rendered, blank_threshold=policy.blank_threshold)
    visual_gate = None
    if reference_pptx is not None:
        visual_gate = render_and_compare(
            reference_pptx,
            pptx,
            workspace / "visual-regression",
            threshold_ssim=policy.visual_ssim,
            threshold_mae=policy.visual_mae,
            threshold_mismatch=policy.visual_mismatch,
        )
    return page_gate, visual_gate


def run_repair_loop(
    build: Callable[[int, list[dict[str, Any]]], Path],
    *,
    workspace: Path,
    reference_pptx: Path | None = None,
    policy: DeliveryPolicy | None = None,
) -> DeliveryReport:
    """Orchestrate build → full-deck QA → repair request → rebuild.

    `build(iteration, repair_requests)` must repair the source/IR and return a new PPTX.
    The loop never patches the final PPTX in-place and never accepts an aggregate score
    when an individual page fails.
    """
    policy = policy or DeliveryPolicy()
    workspace.mkdir(parents=True, exist_ok=True)
    attempts: list[DeliveryAttempt] = []
    repair_requests: list[dict[str, Any]] = []
    final_pptx: Path | None = None
    last_page_gate: DeckGateReport | None = None
    last_visual_gate: VisualReport | None = None

    for iteration in range(1, policy.max_repair_iterations + 1):
        final_pptx = Path(build(iteration, repair_requests))
        attempt_dir = workspace / f"iteration-{iteration}"
        page_gate, visual_gate = validate_delivery(
            final_pptx,
            attempt_dir,
            reference_pptx=reference_pptx,
            policy=policy,
        )
        repair_requests = _repair_requests(page_gate, visual_gate)
        passed = page_gate.passed and (visual_gate is None or visual_gate.passed)
        attempts.append(DeliveryAttempt(
            iteration=iteration,
            pptx=str(final_pptx),
            page_gate_passed=page_gate.passed,
            visual_gate_passed=visual_gate.passed if visual_gate else None,
            failed_pages=sorted({r["page"] for r in repair_requests}),
            repair_requests=repair_requests,
        ))
        last_page_gate, last_visual_gate = page_gate, visual_gate
        if passed:
            report = DeliveryReport(True, iteration, str(final_pptx), attempts,
                                    page_gate.to_dict(), visual_gate.to_dict() if visual_gate else None)
            (workspace / "delivery-report.json").write_text(
                json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            return report

    assert final_pptx is not None
    report = DeliveryReport(False, len(attempts), str(final_pptx), attempts,
                            last_page_gate.to_dict() if last_page_gate else None,
                            last_visual_gate.to_dict() if last_visual_gate else None)
    (workspace / "delivery-report.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
