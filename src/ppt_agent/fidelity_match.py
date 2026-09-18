"""Element Matching Engine: pair reference elements with candidate elements.

Naive index-based sequence comparison turns one local change (an insertion, a
reorder) into cascading false diffs. This module pairs elements by identity
signals, in priority order:

1. stable semantic identity  (element kind + placeholder identity)
2. placeholder identity      (ph type/idx)
3. shape name
4. media content hash
5. semantic role             (same kind + same area class)
6. geometry proximity        (IoU of rendered bboxes)
7. index                     (last-resort fallback, flagged as such)

Output: matched pairs (with the matching method), added, removed and ambiguous
elements, plus reorder detection for matched pairs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

_MATCH_METHOD_PRIORITY = (
    "semantic_identity",
    "placeholder",
    "name",
    "media_hash",
    "role",
    "geometry",
    "index",
)

# IoU above this counts as a geometry-proximity match
GEOMETRY_IOU_THRESHOLD = 0.30


@dataclass(frozen=True)
class MatchedPair:
    reference: dict[str, Any]
    candidate: dict[str, Any]
    method: str
    reference_order: int
    candidate_order: int

    @property
    def reordered(self) -> bool:
        return self.reference_order != self.candidate_order


@dataclass
class MatchResult:
    matched: list[MatchedPair] = field(default_factory=list)
    added: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    ambiguous: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": [
                {
                    "reference": pair.reference.get("shape_id"),
                    "candidate": pair.candidate.get("shape_id"),
                    "method": pair.method,
                    "reference_order": pair.reference_order,
                    "candidate_order": pair.candidate_order,
                    "reordered": pair.reordered,
                }
                for pair in self.matched
            ],
            "added": [element.get("shape_id") for element in self.added],
            "removed": [element.get("shape_id") for element in self.removed],
            "ambiguous": [element.get("shape_id") for element in self.ambiguous],
            "reorder_count": sum(1 for pair in self.matched if pair.reordered),
        }


# --------------------------------------------------------------------------- #
# identity signals
# --------------------------------------------------------------------------- #
def _placeholder_identity(element: dict[str, Any]) -> tuple[str, str] | None:
    ph = element.get("placeholder")
    if not ph:
        return None
    return (str(ph.get("type") or ""), str(ph.get("idx") or ""))


def _semantic_identity(element: dict[str, Any]) -> str | None:
    """Kind + placeholder identity: the most stable authored signal."""
    ph = _placeholder_identity(element)
    if ph:
        return f"{element.get('kind', 'sp')}|{ph[0]}|{ph[1]}"
    return None


def _geometry_key(element: dict[str, Any]) -> tuple[float, float, float, float] | None:
    geometry = element.get("geometry_emu") or element.get("geometry") or {}
    bbox = geometry.get("rendered_bbox") or (
        {"x": geometry.get("x"), "y": geometry.get("y"), "cx": geometry.get("cx"), "cy": geometry.get("cy")}
        if geometry.get("x") is not None
        else None
    )
    if not bbox or bbox.get("cx") is None:
        return None
    return (float(bbox.get("x", 0)), float(bbox.get("y", 0)), float(bbox.get("cx", 0)), float(bbox.get("cy", 0)))


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _media_hash(element: dict[str, Any]) -> str | None:
    media = element.get("media") or {}
    return media.get("sha256") or None


def _semantic_role(element: dict[str, Any]) -> str:
    """Coarse role class: what the element *is*, independent of identity."""
    size = _geometry_key(element)
    area = size[2] * size[3] if size else 0.0
    if area >= (914400.0 ** 2) * 12:
        area_class = "large"
    elif area >= (914400.0 ** 2) * 2:
        area_class = "medium"
    else:
        area_class = "small"
    has_text = bool(element.get("text"))
    return f"{element.get('kind', 'sp')}|{area_class}|{'text' if has_text else 'plain'}"


# --------------------------------------------------------------------------- #
# matching
# --------------------------------------------------------------------------- #
def match_elements(
    reference: Sequence[dict[str, Any]],
    candidate: Sequence[dict[str, Any]],
    *,
    geometry_threshold: float = GEOMETRY_IOU_THRESHOLD,
) -> MatchResult:
    """Pair elements across two layer lists without index cascading."""
    result = MatchResult()
    unmatched_reference = {index: element for index, element in enumerate(reference)}
    unmatched_candidate = {index: element for index, element in enumerate(candidate)}

    for index, element in enumerate(reference):
        element.setdefault("_match_index", index)
    for index, element in enumerate(candidate):
        element.setdefault("_match_index", index)

    def _take(elements: dict[int, dict[str, Any]], key: int) -> dict[str, Any]:
        element = elements.pop(key)
        return element

    methods: Iterable[str] = _MATCH_METHOD_PRIORITY

    for method in methods:
        remaining_reference = dict(unmatched_reference)
        for ref_index, ref_element in remaining_reference.items():
            if ref_index not in unmatched_reference:
                continue
            candidates: list[tuple[float, int, dict[str, Any]]] = []
            for cand_index, cand_element in unmatched_candidate.items():
                if method == "semantic_identity":
                    ref_key = _semantic_identity(ref_element)
                    if not ref_key or ref_key != _semantic_identity(cand_element):
                        continue
                    score = 1.0
                elif method == "placeholder":
                    ref_key = _placeholder_identity(ref_element)
                    if not ref_key or ref_key != _placeholder_identity(cand_element):
                        continue
                    score = 1.0
                elif method == "name":
                    ref_name = (ref_element.get("name") or "").strip().lower()
                    cand_name = (cand_element.get("name") or "").strip().lower()
                    if not ref_name or ref_name != cand_name:
                        continue
                    score = 1.0
                elif method == "media_hash":
                    ref_hash = _media_hash(ref_element)
                    if not ref_hash or ref_hash != _media_hash(cand_element):
                        continue
                    score = 1.0
                elif method == "role":
                    if _semantic_role(ref_element) != _semantic_role(cand_element):
                        continue
                    ref_geom, cand_geom = _geometry_key(ref_element), _geometry_key(cand_element)
                    score = _iou(ref_geom, cand_geom) if ref_geom and cand_geom else 0.5
                    if score < 0.3:
                        continue
                elif method == "geometry":
                    ref_geom, cand_geom = _geometry_key(ref_element), _geometry_key(cand_element)
                    if not ref_geom or not cand_geom:
                        continue
                    score = _iou(ref_geom, cand_geom)
                    if score < geometry_threshold:
                        continue
                else:  # index fallback
                    if cand_index != ref_index:
                        continue
                    score = 0.0
                candidates.append((score, cand_index, cand_element))
            if not candidates:
                continue
            candidates.sort(key=lambda item: (-item[0], item[1]))
            best_score, best_index, best_element = candidates[0]
            if method != "index" and best_score == 0.0:
                continue
            # Strong identity collisions (two candidates claim the same name /
            # placeholder / hash) stay ambiguous; weak methods (role, geometry,
            # index) resolve ties deterministically by lowest candidate index.
            strong = method in ("semantic_identity", "placeholder", "name", "media_hash")
            ties = [c for c in candidates if c[0] == best_score]
            if strong and len(ties) > 1:
                result.ambiguous.append(ref_element)
                unmatched_reference.pop(ref_index)
                for _, tied_index, _ in ties:
                    unmatched_candidate.pop(tied_index, None)
                continue
            result.matched.append(
                MatchedPair(
                    reference=ref_element,
                    candidate=_take(unmatched_candidate, best_index),
                    method=method,
                    # prefer the OOXML z_index (spTree child position) so reorder
                    # evidence doubles as a repair target address
                    reference_order=int(
                        ref_element.get("z_index")
                        if ref_element.get("z_index") is not None
                        else ref_element.get("source_z")
                        if ref_element.get("source_z") is not None
                        else ref_element.get("_match_index", ref_index)
                    ),
                    candidate_order=int(
                        best_element.get("z_index")
                        if best_element.get("z_index") is not None
                        else best_element.get("source_z")
                        if best_element.get("source_z") is not None
                        else best_element.get("_match_index", best_index)
                    ),
                )
            )
            unmatched_reference.pop(ref_index)

    result.added = list(unmatched_candidate.values())
    result.removed = list(unmatched_reference.values())
    for element in (*reference, *candidate):
        element.pop("_match_index", None)
    return result
