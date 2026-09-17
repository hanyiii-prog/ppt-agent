"""Deck-level fidelity gate: extract every slide and compare it structurally."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .fidelity import extract_fidelity_dna
from .fidelity_diff import FidelityReport, compare_dna


def compare_decks(
    reference: str | Path,
    candidate: str | Path,
    *,
    tolerance: float = 0.0005,
) -> dict[str, Any]:
    """Compare all slides in two PPTX packages.

    The result is deterministic and page-addressable. A deck passes only when
    slide count, slide size and every extracted slide DNA payload pass.
    """
    reference = Path(reference)
    candidate = Path(candidate)
    ref_first = extract_fidelity_dna(reference, slide_index=1)
    cand_first = extract_fidelity_dna(candidate, slide_index=1)
    ref_count = ref_first["presentation"]["slide_count"]
    cand_count = cand_first["presentation"]["slide_count"]
    ref_size = ref_first["presentation"]["slide_size_emu"]
    cand_size = cand_first["presentation"]["slide_size_emu"]

    pages: list[dict[str, Any]] = []
    for index in range(1, max(ref_count, cand_count) + 1):
        if index > ref_count or index > cand_count:
            pages.append({"slide_index": index, "passed": False, "issues": [{"path": "slide", "category": "page_kind", "message": "slide missing"}]})
            continue
        report: FidelityReport = compare_dna(
            extract_fidelity_dna(reference, slide_index=index),
            extract_fidelity_dna(candidate, slide_index=index),
            tolerance=tolerance,
        )
        pages.append({"slide_index": index, **report.to_dict()})

    package_issues = []
    if ref_count != cand_count:
        package_issues.append({"path": "presentation.slide_count", "reference": ref_count, "candidate": cand_count, "message": "slide count mismatch"})
    if ref_size != cand_size:
        package_issues.append({"path": "presentation.slide_size_emu", "reference": ref_size, "candidate": cand_size, "message": "slide size mismatch"})

    return {
        "schema": "template-dna/fidelity-gate/v1",
        "passed": not package_issues and all(page["passed"] for page in pages),
        "reference": str(reference),
        "candidate": str(candidate),
        "presentation": {"reference_slide_count": ref_count, "candidate_slide_count": cand_count, "reference_slide_size_emu": ref_size, "candidate_slide_size_emu": cand_size},
        "package_issues": package_issues,
        "pages": pages,
    }


def assert_deck_fidelity(reference: str | Path, candidate: str | Path, *, tolerance: float = 0.0005) -> dict[str, Any]:
    """Raise when the deck-level structural fidelity gate fails."""
    result = compare_decks(reference, candidate, tolerance=tolerance)
    if not result["passed"]:
        failed = next((page for page in result["pages"] if not page["passed"]), None)
        detail = failed.get("issues", [{}])[0] if failed else (result["package_issues"] or [{}])[0]
        raise AssertionError(f"Deck fidelity gate failed: {detail.get('path', 'presentation')}")
    return result


__all__ = ["assert_deck_fidelity", "compare_decks"]
