"""Deterministic structural fidelity comparison for Template DNA.

This module is intentionally separate from :mod:`ppt_agent.fidelity`, which
extracts the low-level OOXML fidelity layer.  The comparator turns two DNA
payloads into path-addressable issues, category summaries, and a bounded score.
Raw XML is excluded from structural equality because equivalent OOXML can be
serialized differently; callers that need byte-level checks should compare the
package/media hashes separately.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
import math

DEFAULT_TOLERANCE = 0.0005
CATEGORIES = (
    "page_kind", "layer_order", "geometry", "style", "text", "media",
    "table", "inheritance", "other",
)
_VOLATILE_KEYS = frozenset({"raw_xml", "xml_sha256"})


@dataclass(frozen=True)
class FidelityIssue:
    path: str
    category: str
    reference: Any
    candidate: Any
    message: str


@dataclass
class FidelityReport:
    passed: bool
    reference_schema: str | None
    candidate_schema: str | None
    issues: list[FidelityIssue] = field(default_factory=list)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def summary(self) -> dict[str, int]:
        out = {name: 0 for name in CATEGORIES}
        for issue in self.issues:
            out[issue.category if issue.category in out else "other"] += 1
        return out

    @property
    def score(self) -> float:
        """Return a simple bounded structural-fidelity score in [0, 100]."""
        if not self.issues:
            return 100.0
        # A few high-level differences should matter, while a noisy page should
        # not drive the score below zero merely because it has many leaf fields.
        weighted = sum(_ISSUE_WEIGHTS.get(i.category, 1.0) for i in self.issues)
        return max(0.0, round(100.0 * math.exp(-weighted / 20.0), 2))

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "reference_schema": self.reference_schema,
            "candidate_schema": self.candidate_schema,
            "issue_count": self.issue_count,
            "summary": self.summary,
            "issues": [issue.__dict__ for issue in self.issues],
        }


_ISSUE_WEIGHTS = {
    "page_kind": 5.0,
    "layer_order": 4.0,
    "geometry": 2.0,
    "style": 1.5,
    "text": 1.0,
    "media": 2.0,
    "table": 1.0,
    "inheritance": 2.0,
    "other": 1.0,
}


def _number_equal(a: Any, b: Any, tolerance: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if isinstance(a, float) and math.isnan(a):
            return isinstance(b, float) and math.isnan(b)
        return abs(float(a) - float(b)) <= tolerance
    return False


def _category(path: str) -> str:
    p = path.lower()
    if "page_kind" in p or ".kind" in p:
        return "page_kind"
    if any(x in p for x in ("render_order", "z_order", "z_index", ".layers")):
        return "layer_order"
    if any(x in p for x in (
        "geometry", "bbox", "left", "top", "width", "height", "rotation", "flip_",
    )):
        return "geometry"
    if any(x in p for x in (
        "fill", "line", "opacity", "alpha", "transparency", "effects", "gradient",
    )):
        return "style"
    if any(x in p for x in (
        "text", "font", "typeface", "body", "autofit", "insets",
    )):
        return "text"
    if any(x in p for x in ("picture", "media", "r_embed", "r_link", "crop", "source_rect")):
        return "media"
    if any(x in p for x in ("table", "cell", "row_", "col_")):
        return "table"
    if any(x in p for x in ("origin", "parent_id", "placeholder", "master", "layout", "inherit")):
        return "inheritance"
    return "other"


def _same(a: Any, b: Any, tolerance: float) -> bool:
    if _number_equal(a, b, tolerance):
        return True
    if type(a) is not type(b):
        return False
    if isinstance(a, Mapping):
        ka = {k for k in a if k not in _VOLATILE_KEYS}
        kb = {k for k in b if k not in _VOLATILE_KEYS}
        return ka == kb and all(_same(a[k], b[k], tolerance) for k in ka)
    if isinstance(a, Sequence) and not isinstance(a, (str, bytes, bytearray)):
        return len(a) == len(b) and all(_same(x, y, tolerance) for x, y in zip(a, b))
    return a == b


def _walk(reference: Any, candidate: Any, path: str, tolerance: float, issues: list[FidelityIssue]) -> None:
    if isinstance(reference, Mapping) and isinstance(candidate, Mapping):
        keys = (set(reference) | set(candidate)) - _VOLATILE_KEYS
        for key in sorted(keys, key=str):
            child = f"{path}.{key}" if path else str(key)
            if key not in reference or key not in candidate:
                issues.append(FidelityIssue(
                    child, _category(child), reference.get(key), candidate.get(key), "key missing",
                ))
            else:
                _walk(reference[key], candidate[key], child, tolerance, issues)
        return
    if isinstance(reference, Sequence) and not isinstance(reference, (str, bytes, bytearray)):
        if not isinstance(candidate, Sequence) or isinstance(candidate, (str, bytes, bytearray)):
            issues.append(FidelityIssue(path, _category(path), reference, candidate, "sequence/type mismatch"))
            return
        if len(reference) != len(candidate):
            issues.append(FidelityIssue(
                path, _category(path), len(reference), len(candidate), "sequence length mismatch",
            ))
        for i, (r, c) in enumerate(zip(reference, candidate)):
            _walk(r, c, f"{path}[{i}]", tolerance, issues)
        return
    if not _same(reference, candidate, tolerance):
        issues.append(FidelityIssue(
            path, _category(path), reference, candidate, "value mismatch",
        ))


def compare_dna(
    reference: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> FidelityReport:
    """Compare two DNA payloads; stacking/page order remains significant."""
    if tolerance < 0:
        raise ValueError("tolerance must be >= 0")
    issues: list[FidelityIssue] = []
    _walk(reference, candidate, "", tolerance, issues)
    return FidelityReport(
        passed=not issues,
        reference_schema=reference.get("schema") or reference.get("version"),
        candidate_schema=candidate.get("schema") or candidate.get("version"),
        issues=issues,
    )


def assert_fidelity(
    reference: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> FidelityReport:
    """Raise :class:`AssertionError` when structural fidelity fails."""
    report = compare_dna(reference, candidate, tolerance=tolerance)
    if not report.passed:
        first = report.issues[0]
        raise AssertionError(
            f"Template DNA fidelity failed ({report.issue_count} issues); "
            f"first: {first.path}: {first.message}"
        )
    return report


__all__ = [
    "CATEGORIES", "DEFAULT_TOLERANCE", "FidelityIssue", "FidelityReport",
    "assert_fidelity", "compare_dna",
]
