from __future__ import annotations

from typing import Any


WEIGHTS = {
    "geometry": 0.35,
    "z_order": 0.20,
    "assets": 0.20,
    "surface": 0.15,
    "raw_xml": 0.10,
}


def _ratio(value: int, total: int) -> float:
    return 1.0 if total == 0 else max(0.0, min(1.0, value / total))


def calculate_fidelity_score(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Calculate a deterministic fidelity score between two fidelity DNA snapshots.

    This is intentionally package-level rather than image-based: it gives the
    renderer a stable regression signal before pixel comparison is introduced.
    """
    ref_shapes = reference.get("slide", {}).get("shapes", [])
    out_shapes = candidate.get("slide", {}).get("shapes", [])

    ref_count = len(ref_shapes)
    matched_geometry = sum(
        1
        for r, c in zip(ref_shapes, out_shapes)
        if r.get("geometry_emu") == c.get("geometry_emu")
    )
    matched_z = sum(
        1
        for r, c in zip(ref_shapes, out_shapes)
        if r.get("z_index") == c.get("z_index")
    )

    ref_assets = set(reference.get("assets", {}).keys())
    out_assets = set(candidate.get("assets", {}).keys())

    metrics = {
        "geometry": _ratio(matched_geometry, ref_count),
        "z_order": _ratio(matched_z, ref_count),
        "assets": _ratio(len(ref_assets & out_assets), len(ref_assets)),
        "surface": 1.0 if reference.get("surface_role") == candidate.get("surface_role") else 0.0,
        "raw_xml": 1.0 if bool(candidate.get("slide", {}).get("raw_xml")) else 0.0,
    }
    score = sum(metrics[key] * weight for key, weight in WEIGHTS.items())

    return {
        "score": round(score, 4),
        "grade": "pass" if score >= 0.9 else "review" if score >= 0.7 else "fail",
        "metrics": metrics,
    }
