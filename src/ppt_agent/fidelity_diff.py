"""Structural Diff 2.0: matching-based, taxonomy-classified fidelity comparison.

The comparator pairs elements with the Element Matching Engine before walking
properties, so a reorder or an insertion no longer cascades into false diffs
on every later index. Differences are classified with the Diff Taxonomy
(PAGE / LAYER / GEOMETRY / STYLE / TEXT / MEDIA / INHERITANCE / STRUCTURE)
through stable issue codes, and raw OOXML evidence is compared through a
semantic canonicalization (namespace- and attribute-order-insensitive) rather
than byte equality.

Package-local identifiers (relationship IDs, paths) remain ignored; geometry,
alpha, z-order, inheritance, media hashes and crop rectangles are compared.
"""
from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .fidelity_match import match_elements

DEFAULT_TOLERANCE = 0.0005
CATEGORIES = ("page_kind", "layer_order", "geometry", "style", "text", "media", "table", "inheritance", "other")
_VOLATILE_KEYS = frozenset({
    "raw_xml", "xml_sha256", "source", "path", "relationship_id", "relationships_xml",
    "target", "package_path", "layout_path", "master_path", "theme_path", "slide_path",
    "spPr_xml", "text_body_xml", "custom_geometry_xml",
})
_ISSUE_WEIGHTS = {
    "page_kind": 5.0, "layer_order": 4.0, "geometry": 2.0, "style": 1.5, "text": 1.0,
    "media": 2.0, "table": 1.0, "inheritance": 2.0, "other": 1.0,
}
_SHAPE_CONTAINERS = ("slide", "master", "layout")
_VOLID_ATTRS = frozenset({"id", "name"})

_NS_PREFIX_RE = re.compile(r"\{[^}]*\}")


@dataclass(frozen=True)
class FidelityIssue:
    path: str
    category: str
    reference: Any
    candidate: Any
    message: str
    code: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = self.__dict__.copy()
        payload["code"] = self.code
        return payload


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
    def codes(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for issue in self.issues:
            out[issue.code or issue.category] = out.get(issue.code or issue.category, 0) + 1
        return out

    @property
    def score(self) -> float:
        if not self.issues:
            return 100.0
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
            "codes": self.codes,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _number_equal(a: Any, b: Any, tolerance: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if isinstance(a, float) and math.isnan(a):
            return isinstance(b, float) and math.isnan(b)
        return abs(float(a) - float(b)) <= tolerance
    return False


_CONTAINER_PREFIX_RE = re.compile(r"^(slide|master|layout)\.shapes\[")


def _category(path: str) -> str:
    p = _CONTAINER_PREFIX_RE.sub("", path.lower())
    if "page_kind" in p or ".kind" in p: return "page_kind"
    if any(x in p for x in ("render_order", "z_order", "z_index", ".layers")): return "layer_order"
    if "custom_geometry" in p or "custgeom" in p: return "other"
    if any(x in p for x in ("text", "font", "typeface", "body", "autofit", "insets", "typography", "paragraph", "runs", "bold", "italic", "underline", "strike", "baseline", "kern", "language", "content")): return "text"
    if any(x in p for x in ("style", "fill", "line", "opacity", "alpha", "transparency", "effects", "gradient", "dash", "arrow")): return "style"
    if any(x in p for x in ("geometry", "bbox", "left", "top", "width", "height", "rotation", "flip_")): return "geometry"
    if any(x in p for x in ("picture", "media", "r_embed", "r_link", "crop", "source_rect", "sha256")): return "media"
    if any(x in p for x in ("table", "cell", "row_", "col_")): return "table"
    if any(x in p for x in ("origin", "parent_id", "placeholder", "master", "layout", "inherit")): return "inheritance"
    return "other"


def _code(path: str, category: str) -> str:
    """Fine-grained Diff Taxonomy code for an issue path."""
    p = path.lower()
    tail = p.rsplit(".", 1)[-1].split("[")[0]
    if category == "page_kind":
        return "page.page_kind"
    if category == "layer_order":
        if "shape missing" in p or p.endswith("slide"):
            return "layer.missing"
        if tail in ("z_index", "global_render_order", "stack"):
            return "layer.reordered"
        return "layer.reordered"
    if category == "geometry":
        if "rotation" in tail: return "geometry.rotation"
        if "flip" in tail: return "geometry.flip"
        if "bbox" in p: return "geometry.bbox"
        if "group" in p: return "geometry.group_transform"
        if tail in ("x", "y"): return "geometry.position"
        if tail in ("cx", "cy", "w", "h"): return "geometry.size"
        return "geometry.position"
    if category == "style":
        if "gradient" in p or tail == "angle" or "stops" in p or "fill_to_rect" in p: return "style.gradient"
        if "alpha" in p or "opacity" in p or "transparency" in p: return "style.alpha"
        if "line" in p or "dash" in p or "arrow" in p: return "style.line"
        if "effect" in p: return "style.effect"
        return "style.fill"
    if category == "text":
        if "autofit" in p: return "text.autofit"
        if "font_size" in tail: return "text.font_size"
        if tail in ("bold", "italic", "underline", "strike", "baseline"): return "text.font"
        if "font" in tail or "typeface" in tail: return "text.font"
        if tail in ("color", "rgb", "scheme"): return "text.color"
        if "body" in p and tail in ("anchor", "wrap", "lins", "rins", "tins", "bins", "vert", "rot", "body"): return "text.bodypr"
        if tail == "text" or "content" in tail: return "text.content"
        if "paragraph" in p or "align" in tail: return "text.paragraph"
        return "text.font"
    if category == "media":
        if "crop" in p or "source_rect" in p: return "media.crop"
        if "alpha" in p: return "media.alpha"
        if "rotation" in p or "flip" in p or "transform" in p: return "media.transform"
        if "sha256" in p or "byte_size" in p or "content_type" in p or "asset" in p: return "media.asset"
        return "media.asset"
    if category == "inheritance":
        if "placeholder" in p: return "inheritance.placeholder"
        if "master" in p: return "inheritance.master"
        if "layout" in p: return "inheritance.layout"
        if "theme" in p: return "inheritance.theme"
        return "inheritance.layout"
    if category == "table":
        return "structure.table"
    if "custom_geometry" in p or "custgeom" in p: return "structure.custom_geometry"
    if "connector" in p: return "structure.connector"
    if category == "other" and "semantic" in p: return "structure.semantic_xml"
    return f"{category}.{tail or 'mismatch'}"


# --------------------------------------------------------------------------- #
# semantic XML canonicalization
# --------------------------------------------------------------------------- #
def _canonicalize_node(node: ET.Element) -> str:
    tag = _NS_PREFIX_RE.sub("", node.tag)
    attrs = sorted(
        (_NS_PREFIX_RE.sub("", key), str(value))
        for key, value in node.attrib.items()
        if _NS_PREFIX_RE.sub("", key).lower() not in _VOLID_ATTRS
    )
    parts = [tag, " ".join(f"{k}={v}" for k, v in attrs)]
    children = [_canonicalize_node(child) for child in node]
    text = (node.text or "").strip()
    return f"{tag}[{'|'.join(parts[1:])}]{{{text}}}[{''.join(children)}]"


def semantic_canonical_xml(xml_string: str | None) -> str | None:
    """Namespace- and attribute-order-insensitive canonical form of raw XML."""
    if not xml_string:
        return None
    try:
        node = ET.fromstring(xml_string)
    except ET.ParseError:
        return None
    return _canonicalize_node(node)


def semantic_xml_hash(xml_string: str | None) -> str | None:
    canonical = semantic_canonical_xml(xml_string)
    if canonical is None:
        return None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# canonicalization
# --------------------------------------------------------------------------- #
def _canonical_assets(assets: Any) -> Any:
    """Media assets are compared by content: {sha256, size}, order-independent."""
    if isinstance(assets, Mapping):
        entries = []
        for value in assets.values():
            if isinstance(value, Mapping):
                entries.append({"sha256": value.get("sha256"), "size": value.get("size")})
        return sorted(entries, key=lambda item: str(item.get("sha256")))
    return assets


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        if set(value) and all(str(k).startswith("ppt/") or "media/" in str(k) for k in value) and all(
            isinstance(v, Mapping) and "sha256" in v for v in value.values()
        ):
            return _canonical_assets(value)
        return {k: _canonical(v) for k, v in value.items() if k not in _VOLATILE_KEYS}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical(v) for v in value]
    return value


def normalize_dna(dna: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize package-local IDs/paths while preserving ordering and hashes."""
    return _canonical(dna)


# --------------------------------------------------------------------------- #
# comparison
# --------------------------------------------------------------------------- #
def _walk(reference: Any, candidate: Any, path: str, tolerance: float, issues: list[FidelityIssue]) -> None:
    if isinstance(reference, Mapping) and isinstance(candidate, Mapping):
        for key in sorted(set(reference) | set(candidate), key=str):
            child = f"{path}.{key}" if path else str(key)
            if key not in reference or key not in candidate:
                issues.append(FidelityIssue(child, _category(child), _safe(reference.get(key)), _safe(candidate.get(key)), "key missing", _code(child, _category(child))))
            else:
                _walk(reference[key], candidate[key], child, tolerance, issues)
        return
    if isinstance(reference, Sequence) and not isinstance(reference, (str, bytes, bytearray)):
        if not isinstance(candidate, Sequence) or isinstance(candidate, (str, bytes, bytearray)):
            issues.append(FidelityIssue(path, _category(path), _safe(reference), _safe(candidate), "sequence/type mismatch", _code(path, _category(path))))
            return
        if len(reference) != len(candidate):
            issues.append(FidelityIssue(path, _category(path), len(reference), len(candidate), "sequence length mismatch", _code(path, _category(path))))
        for i, (r, c) in enumerate(zip(reference, candidate)):
            _walk(r, c, f"{path}[{i}]", tolerance, issues)
        return
    if not _number_equal(reference, candidate, tolerance) and reference != candidate:
        issues.append(FidelityIssue(path, _category(path), _safe(reference), _safe(candidate), "value mismatch", _code(path, _category(path))))


def _safe(value: Any) -> Any:
    """Truncate raw XML payloads in issue evidence so reports stay readable."""
    if isinstance(value, str) and (value.startswith("<") or value[:1] in ("<",)):
        return f"<xml len={len(value)}>"
    return value


def _element_token(element: dict[str, Any]) -> str:
    """Identity token for a diff path: OOXML shape id, falling back to z-index."""
    shape_id = element.get("shape_id")
    if shape_id:
        return f"id={shape_id}"
    return f"z{element.get('z_index', 0)}"


def _compare_shape_lists(
    reference: Sequence[dict[str, Any]],
    candidate: Sequence[dict[str, Any]],
    prefix: str,
    tolerance: float,
    issues: list[FidelityIssue],
) -> None:
    match = match_elements(list(reference), list(candidate))
    category = _category(prefix)
    for element in match.added:
        path = f"{prefix}.added[{element.get('shape_id')}]"
        issues.append(FidelityIssue(path, category, None, element.get("name") or element.get("shape_id"), "layer added", "layer.added"))
    for element in match.removed:
        path = f"{prefix}.removed[{element.get('shape_id')}]"
        issues.append(FidelityIssue(path, category, element.get("name") or element.get("shape_id"), None, "layer removed", "layer.removed"))
    for pair in match.matched:
        base = f"{prefix}[{_element_token(pair.reference)}]"
        if pair.reordered:
            issues.append(
                FidelityIssue(
                    base,
                    category,
                    pair.reference_order,
                    pair.candidate_order,
                    "layer reordered",
                    "layer.reordered",
                )
            )
        _walk(pair.reference, pair.candidate, base, tolerance, issues)
        ref_raw = pair.reference.get("raw_xml")
        cand_raw = pair.candidate.get("raw_xml")
        if ref_raw and cand_raw:
            ref_hash = semantic_xml_hash(ref_raw)
            cand_hash = semantic_xml_hash(cand_raw)
            if ref_hash and cand_hash and ref_hash != cand_hash:
                issues.append(
                    FidelityIssue(
                        f"{base}.semantic_xml",
                        "other",
                        ref_hash,
                        cand_hash,
                        "semantic XML mismatch",
                        "structure.semantic_xml",
                    )
                )


def _compare_payloads(reference: Any, candidate: Any, path: str, tolerance: float, issues: list[FidelityIssue]) -> None:
    if (
        isinstance(reference, Mapping)
        and isinstance(candidate, Mapping)
        and "shapes" in reference
        and "shapes" in candidate
        and isinstance(reference["shapes"], Sequence)
        and isinstance(candidate["shapes"], Sequence)
    ):
        _compare_shape_lists(reference["shapes"], candidate["shapes"], f"{path}.shapes", tolerance, issues)
        rest_ref = {k: v for k, v in reference.items() if k != "shapes"}
        rest_cand = {k: v for k, v in candidate.items() if k != "shapes"}
        _walk(rest_ref, rest_cand, path, tolerance, issues)
        return
    _walk(reference, candidate, path, tolerance, issues)


def compare_dna(reference: Mapping[str, Any], candidate: Mapping[str, Any], *, tolerance: float = DEFAULT_TOLERANCE) -> FidelityReport:
    """Compare two DNA payloads with matching-based element pairing."""
    if tolerance < 0:
        raise ValueError("tolerance must be >= 0")
    reference = normalize_dna(reference)
    candidate = normalize_dna(candidate)
    issues: list[FidelityIssue] = []
    for key in sorted(set(reference) | set(candidate), key=str):
        child = str(key)
        if key not in reference or key not in candidate:
            category = _category(child)
            issues.append(FidelityIssue(child, category, _safe(reference.get(key) if isinstance(reference, Mapping) else None), _safe(candidate.get(key) if isinstance(candidate, Mapping) else None), "key missing", _code(child, category)))
            continue
        if child in _SHAPE_CONTAINERS:
            _compare_payloads(reference[key], candidate[key], child, tolerance, issues)
        else:
            _walk(reference[key], candidate[key], child, tolerance, issues)
    return FidelityReport(
        not issues,
        reference.get("schema") or reference.get("version") if isinstance(reference, Mapping) else None,
        candidate.get("schema") or candidate.get("version") if isinstance(candidate, Mapping) else None,
        issues,
    )


def assert_fidelity(reference: Mapping[str, Any], candidate: Mapping[str, Any], *, tolerance: float = DEFAULT_TOLERANCE) -> FidelityReport:
    report = compare_dna(reference, candidate, tolerance=tolerance)
    if not report.passed:
        first = report.issues[0]
        raise AssertionError(f"Template DNA fidelity failed ({report.issue_count} issues); first: {first.path}: {first.message}")
    return report


__all__ = [
    "CATEGORIES",
    "DEFAULT_TOLERANCE",
    "FidelityIssue",
    "FidelityReport",
    "assert_fidelity",
    "compare_dna",
    "normalize_dna",
    "semantic_canonical_xml",
    "semantic_xml_hash",
]
