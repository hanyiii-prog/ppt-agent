from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ir import validate_presentation


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    message: str
    slide_id: str | None = None
    component_id: str | None = None


@dataclass
class QAReport:
    findings: list[Finding] = field(default_factory=list)
    checks: int = 0

    @property
    def passed(self) -> bool:
        return not any(item.severity == "error" for item in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": self.checks,
            "findings": [item.__dict__ for item in self.findings],
        }


def validate_ir(data: dict[str, Any]) -> QAReport:
    report = QAReport()
    errors = validate_presentation(data)
    report.checks += 3
    report.findings.extend(Finding("schema", "error", message) for message in errors)
    slides = data.get("slides", [])
    if not isinstance(slides, list):
        return report

    seen_ids: set[str] = set()
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        report.checks += 1
        slide_id = slide.get("id")
        if slide_id in seen_ids:
            report.findings.append(Finding("identity", "error", "duplicate slide id", slide_id=slide_id))
        if slide_id:
            seen_ids.add(slide_id)
        for component in slide.get("components", []):
            if not isinstance(component, dict):
                continue
            report.checks += 1
            for key in ("x", "y", "w", "h"):
                value = component.get(key)
                if value is not None and (not isinstance(value, (int, float)) or value != value):
                    report.findings.append(Finding("geometry", "error", f"{key} must be numeric", slide_id=slide_id, component_id=component.get("id")))
            if component.get("w") is not None and component.get("w") < 0:
                report.findings.append(Finding("geometry", "error", "negative width", slide_id=slide_id, component_id=component.get("id")))
            if component.get("h") is not None and component.get("h") < 0:
                report.findings.append(Finding("geometry", "error", "negative height", slide_id=slide_id, component_id=component.get("id")))
    return report
