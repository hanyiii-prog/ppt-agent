"""Deterministic structural fidelity comparison for Template DNA.

The comparator normalizes package-local identifiers before walking DNA. PowerPoint
relationship IDs, source paths and raw XML serialization are implementation
details; geometry, alpha, z-order, inheritance, crop and media hashes remain
fidelity evidence and are compared.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
import math

DEFAULT_TOLERANCE = 0.0005
CATEGORIES = ("page_kind", "layer_order", "geometry", "style", "text", "media", "table", "inheritance", "other")
_VOLATILE_KEYS = frozenset({"raw_xml", "xml_sha256", "source", "path", "relationship_id", "relationships_xml"})
_ISSUE_WEIGHTS = {"page_kind": 5.0, "layer_order": 4.0, "geometry": 2.0, "style": 1.5, "text": 1.0, "media": 2.0, "table": 1.0, "inheritance": 2.0, "other": 1.0}

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
        if not self.issues:
            return 100.0
        weighted = sum(_ISSUE_WEIGHTS.get(i.category, 1.0) for i in self.issues)
        return max(0.0, round(100.0 * math.exp(-weighted / 20.0), 2))

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "score": self.score, "reference_schema": self.reference_schema, "candidate_schema": self.candidate_schema, "issue_count": self.issue_count, "summary": self.summary, "issues": [issue.__dict__ for issue in self.issues]}


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
    if "page_kind" in p or ".kind" in p: return "page_kind"
    if any(x in p for x in ("render_order", "z_order", "z_index", ".layers")): return "layer_order"
    if any(x in p for x in ("geometry", "bbox", "left", "top", "width", "height", "rotation", "flip_")): return "geometry"
    if any(x in p for x in ("style", "fill", "line", "opacity", "alpha", "transparency", "effects", "gradient")): return "style"
    if any(x in p for x in ("text", "font", "typeface", "body", "autofit", "insets")): return "text"
    if any(x in p for x in ("picture", "media", "r_embed", "r_link", "crop", "source_rect", "sha256")): return "media"
    if any(x in p for x in ("table", "cell", "row_", "col_")): return "table"
    if any(x in p for x in ("origin", "parent_id", "placeholder", "master", "layout", "inherit")): return "inheritance"
    return "other"


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _canonical(v) for k, v in value.items() if k not in _VOLATILE_KEYS}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical(v) for v in value]
    return value


def normalize_dna(dna: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize package-local IDs/paths while preserving ordering and hashes."""
    return _canonical(dna)


def _walk(reference: Any, candidate: Any, path: str, tolerance: float, issues: list[FidelityIssue]) -> None:
    if isinstance(reference, Mapping) and isinstance(candidate, Mapping):
        for key in sorted(set(reference) | set(candidate), key=str):
            child = f"{path}.{key}" if path else str(key)
            if key not in reference or key not in candidate:
                issues.append(FidelityIssue(child, _category(child), reference.get(key), candidate.get(key), "key missing"))
            else:
                _walk(reference[key], candidate[key], child, tolerance, issues)
        return
    if isinstance(reference, Sequence) and not isinstance(reference, (str, bytes, bytearray)):
        if not isinstance(candidate, Sequence) or isinstance(candidate, (str, bytes, bytearray)):
            issues.append(FidelityIssue(path, _category(path), reference, candidate, "sequence/type mismatch"))
            return
        if len(reference) != len(candidate):
            issues.append(FidelityIssue(path, _category(path), len(reference), len(candidate), "sequence length mismatch"))
        for i, (r, c) in enumerate(zip(reference, candidate)):
            _walk(r, c, f"{path}[{i}]", tolerance, issues)
        return
    if not _number_equal(reference, candidate, tolerance) and reference != candidate:
        issues.append(FidelityIssue(path, _category(path), reference, candidate, "value mismatch"))


def compare_dna(reference: Mapping[str, Any], candidate: Mapping[str, Any], *, tolerance: float = DEFAULT_TOLERANCE) -> FidelityReport:
    """Compare two DNA payloads; list order is significant, including z-order."""
    if tolerance < 0:
        raise ValueError("tolerance must be >= 0")
    reference = normalize_dna(reference)
    candidate = normalize_dna(candidate)
    issues: list[FidelityIssue] = []
    _walk(reference, candidate, "", tolerance, issues)
    return FidelityReport(not issues, reference.get("schema") or reference.get("version"), candidate.get("schema") or candidate.get("version"), issues)


def assert_fidelity(reference: Mapping[str, Any], candidate: Mapping[str, Any], *, tolerance: float = DEFAULT_TOLERANCE) -> FidelityReport:
    report = compare_dna(reference, candidate, tolerance=tolerance)
    if not report.passed:
        first = report.issues[0]
        raise AssertionError(f"Template DNA fidelity failed ({report.issue_count} issues); first: {first.path}: {first.message}")
    return report

__all__ = ["CATEGORIES", "DEFAULT_TOLERANCE", "FidelityIssue", "FidelityReport", "assert_fidelity", "compare_dna", "normalize_dna"]
