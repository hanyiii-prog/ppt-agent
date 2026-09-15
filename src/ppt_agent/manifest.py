from __future__ import annotations

from pathlib import Path
from typing import Any

from .delivery import DeliveryReport


def page_role(page: int, slide_count: int) -> str:
    if page == 1:
        return "first"
    if page == slide_count:
        return "last"
    return "body"


def build_manifest(report: DeliveryReport, *, reference: Path | None = None) -> dict[str, Any]:
    """Flatten the final production report into a stable per-page delivery manifest."""
    pages: dict[int, dict[str, Any]] = {}
    page_gate = report.page_gate or {}
    critic_gate = report.critic_gate or {}
    visual_gate = report.visual_gate or {}
    slide_count = int(page_gate.get("slide_count", 0))

    for page in page_gate.get("pages", []):
        number = int(page["page"])
        pages[number] = {
            "page": number,
            "role": page_role(number, slide_count),
            "passed": bool(page.get("passed")),
            "gates": {
                "structure": bool(page.get("passed")),
                "critic": True,
                "visual_regression": None,
            },
            "findings": [],
            "artifacts": {},
        }
        if page.get("issues"):
            pages[number]["findings"].extend({"kind": "page_gate", "message": x} for x in page["issues"])

    for finding in critic_gate.get("findings", []):
        number = int(finding["page"])
        item = pages.setdefault(number, {
            "page": number, "role": page_role(number, slide_count), "passed": True,
            "gates": {"structure": True, "critic": True, "visual_regression": None},
            "findings": [], "artifacts": {},
        })
        item["gates"]["critic"] = finding.get("severity") != "error"
        item["findings"].append({"kind": "visual_critic", **finding})
        if finding.get("severity") == "error":
            item["passed"] = False

    for page in visual_gate.get("pages", []):
        number = int(page["page"])
        item = pages.setdefault(number, {
            "page": number, "role": page_role(number, slide_count), "passed": True,
            "gates": {"structure": True, "critic": True, "visual_regression": True},
            "findings": [], "artifacts": {},
        })
        item["gates"]["visual_regression"] = bool(page.get("passed"))
        item["findings"].append({"kind": "visual_regression", **page})
        if page.get("diff_image"):
            item["artifacts"]["diff_image"] = page["diff_image"]
        if not page.get("passed"):
            item["passed"] = False

    return {
        "schema_version": "1.0",
        "candidate": report.final_pptx,
        "reference": str(reference) if reference else None,
        "passed": report.passed and all(item["passed"] for item in pages.values()),
        "iterations": report.iterations,
        "pages": [pages[number] for number in sorted(pages)],
        "attempts": [attempt.__dict__ for attempt in report.attempts],
    }
