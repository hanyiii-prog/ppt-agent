from __future__ import annotations

from typing import Any


def build_final_report(
    quality: dict[str, Any],
    template: dict[str, Any],
    planning_report: dict[str, Any],
    *,
    degradations: list[str] | None = None,
    repairs: list[dict[str, Any]] | None = None,
    artifacts: dict[str, Any] | None = None,
    template_route: str = "builtin-composition",
) -> dict[str, Any]:
    return {
        "schema": "ppt-agent-v3-report/v1",
        "status": quality.get("status", "failed"),
        "page_total": quality.get("structural_quality", {}).get("page_total", 0),
        "model": {
            "content": "used" if planning_report.get("mode") == "model" else "off",
            "vision": quality.get("visual_quality", {}).get("model_review", "unavailable"),
        },
        "template": {
            "id": template.get("id"),
            "source": template.get("source_kind"),
            "score": (template.get("selection") or {}).get("score"),
            "route": template_route,
        },
        "planning": planning_report,
        "content_quality": quality.get("content_quality", {}),
        "structural_quality": quality.get("structural_quality", {}),
        "editability": quality.get("editability", {}),
        "visual_quality": quality.get("visual_quality", {}),
        "render": quality.get("render", {}),
        "degradations": degradations or [],
        "repairs": repairs or [],
        "artifacts": artifacts or {},
    }


__all__ = ["build_final_report"]
