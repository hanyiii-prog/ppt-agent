from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

from .delivery import DeliveryPolicy, run_repair_loop


def repair_and_rebuild(
    build: Callable[[int, list[dict[str, Any]]], Path],
    *,
    workspace: str | Path,
    critic: Any | None = None,
    visual_review_reason: str | None = None,
    max_iterations: int = 3,
    reference_pptx: str | Path | None = None,
) -> dict[str, Any]:
    """Build, render, inspect, repair the source spec, rebuild, and recheck."""
    report = run_repair_loop(
        build,
        workspace=Path(workspace),
        reference_pptx=Path(reference_pptx) if reference_pptx else None,
        policy=DeliveryPolicy(max_repair_iterations=max_iterations),
        critic=critic,
        visual_review_reason=visual_review_reason,
    )
    return report.to_dict()


def apply_repair_requests(
    design_ir: dict[str, Any],
    repair_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply bounded design-level repairs without changing source facts."""
    repaired = copy.deepcopy(design_ir)
    touched: list[str] = []
    for request in repair_requests or []:
        page_no = request.get("page")
        if isinstance(page_no, bool) or not isinstance(page_no, int) or not 1 <= page_no <= len(repaired.get("pages") or []):
            continue
        page = repaired["pages"][page_no - 1]
        rules = {
            request.get("rule"),
            *(
                item.get("rule") if isinstance(item, dict) else str(item)
                for item in request.get("issues") or []
            ),
        }
        overflow = "dense_content" in rules or any(
            "overflow" in str(item).lower() for item in request.get("issues") or []
        )
        if overflow:
            page["layout_variant"] = "wide"
            touched.append(f"{page.get('page_id')}:layout_variant")
            for slot in page.get("slots", {}).values():
                slot_id = str(slot.get("id") or "")
                if slot_id == "body":
                    slot["x"] = 0.5
                    slot["w"] = 12.333
                    slot["y"] = min(float(slot.get("y", 2.4)), 2.25)
                    slot["h"] = min(float(slot.get("h", 4.2)) + 0.3, 4.85)
                    touched.append(f"{page.get('page_id')}:body:geometry")
        for slot in page.get("slots", {}).values():
            if slot.get("font") in {"body", "takeaway"}:
                if overflow:
                    current = float(slot.get("size_pt", 18.0))
                    slot["size_pt"] = max(16.0, current * 0.92)
                    touched.append(f"{page.get('page_id')}:{slot.get('id')}:font")
    repaired.setdefault("repair_history", []).append({
        "requests": len(repair_requests or []),
        "touched": touched,
    })
    return repaired


__all__ = ["apply_repair_requests", "repair_and_rebuild"]
