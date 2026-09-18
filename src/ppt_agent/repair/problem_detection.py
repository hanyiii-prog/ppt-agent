"""Problem model + detection: one shape for everything that can be repaired.

Sources unified here:
* constraint violations (batch 3.D ``constraint_engine``) -- geometry truth;
* external findings passed in by callers: ``audit_pages`` issue dicts
  (``kind``/``detail``) and ``design_rules.validate_design`` findings
  (``code``/``detail``/``severity``).

A ``Problem`` carries a stable signature (code + target) so the scheduler can
detect oscillation: if the same signature survives a repair round, the repair
is not working and the cycle must stop and say so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..layout.constraint_engine import violations_summary


@dataclass(frozen=True)
class Problem:
    code: str                       # e.g. "overlap", "out_of_bounds", "R-TYPO-001", "audit:collision"
    severity: str                   # high / medium / low
    target_kind: str                # "element" / "page"
    target_id: str                  # element index or page identifier
    message: str
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def signature(self) -> str:
        return f"{self.code}:{self.target_kind}:{self.target_id}"


def problems_from_constraints(violations: list[dict[str, Any]]) -> list[Problem]:
    severity_by_kind = {
        "out_of_bounds": "high",
        "overlap": "high",
        "margin_breach": "medium",
        "min_gap": "low",
    }
    problems: list[Problem] = []
    for violation in violations:
        kind = str(violation.get("kind") or "unknown")
        other = violation.get("other")
        target_id = str(violation.get("index", 0)) + (f"+{other}" if other is not None else "")
        problems.append(Problem(
            code=kind,
            severity=severity_by_kind.get(kind, "medium"),
            target_kind="element",
            target_id=target_id,
            message=str(violation.get("detail") or kind),
            payload={key: value for key, value in violation.items() if key not in ("kind", "detail")},
        ))
    return problems


def _from_external_finding(finding: dict[str, Any]) -> Problem | None:
    if "code" in finding and str(finding["code"]).startswith("R-"):
        return Problem(
            code=str(finding["code"]),
            severity=str(finding.get("severity") or "medium"),
            target_kind="element",
            target_id=str(finding.get("target") or finding.get("detail") or "")[:64],
            message=str(finding.get("detail") or ""),
            payload={key: value for key, value in finding.items() if key not in ("code", "detail", "severity")},
        )
    if "kind" in finding:  # audit_pages issue shape
        return Problem(
            code=f"audit:{finding['kind']}",
            severity="high" if finding["kind"] in ("overflow", "collision") else "medium",
            target_kind="page",
            target_id=str(finding.get("slide") or finding.get("page") or "*"),
            message=str(finding.get("detail") or finding["kind"]),
            payload={key: value for key, value in finding.items() if key not in ("kind", "detail")},
        )
    return None


def collect_problems(
    boxes: list[dict[str, Any]],
    width_in: float,
    height_in: float,
    *,
    external: list[dict[str, Any]] | None = None,
    margin_in: float = 0.7,
    min_gap_in: float = 0.08,
) -> list[Problem]:
    """All repairable problems of one page: geometry + normalized externals."""
    from ..layout.constraint_engine import check_constraints

    problems = problems_from_constraints(
        check_constraints(boxes, width_in, height_in, margin_in=margin_in, min_gap_in=min_gap_in)
    )
    for finding in external or []:
        problem = _from_external_finding(finding)
        if problem is not None:
            problems.append(problem)
    return problems


def problems_summary(problems: list[Problem]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for problem in problems:
        summary[problem.code] = summary.get(problem.code, 0) + 1
    return dict(sorted(summary.items()))


__all__ = ["Problem", "collect_problems", "problems_summary", "problems_from_constraints", "violations_summary"]
