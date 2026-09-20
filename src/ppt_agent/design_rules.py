"""Design rules: one merged, machine-checkable rulebook per template.

Why this exists
---------------
Batch 1's extractors each answer one question; the repair layer (3.E) and QA
need one payload that says "what this template does" in checkable form:
which sizes belong to the type scale, which colours belong to the palette,
which gaps are the template's rhythm, where the alignment lines are.

``build_design_rules`` composes the v1.0 design DNA into
``design-rules/v1``; ``validate_design`` checks a *candidate* deck against it
and returns explicit findings (never silent passes). Pure rules -- no LLM.
"""

from __future__ import annotations

from typing import Any

SCHEMA = "design-rules/v1"


def build_design_rules(
    design_dna: dict[str, Any], spacing_graph: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Compose a ``template-dna/v1.0`` design segment into a rulebook.

    ``spacing_graph`` (from ``spacing_graph.build_spacing_graph``) is optional;
    when given, the template's dominant gaps become checkable rhythm rules.
    """
    segment = design_dna.get("design_dna") or design_dna
    typography = segment.get("typography") or {}
    color = segment.get("color") or {}
    shape = segment.get("shape") or {}
    layout = segment.get("layout") or {}

    named_scale = typography.get("scale_named") or {}
    allowed_sizes = sorted(
        {float(value) for value in named_scale.values() if isinstance(value, (int, float))}
    )
    allowed_hex = sorted(
        {
            hex_value
            for hex_value in (color.get("named") or {}).values()
            if isinstance(hex_value, str) and len(hex_value) == 6
        }
    )
    census_hex = [
        entry.get("rgb") for entry in (color.get("census") or []) if entry.get("rgb")
    ]

    return {
        "schema": SCHEMA,
        "typography": {
            "scale_named": named_scale,
            "allowed_sizes_pt": allowed_sizes,
            "families": typography.get("families") or [],
        },
        "color": {
            "named": color.get("named") or {},
            "allowed_hex": allowed_hex,
            "census_hex": census_hex,
        },
        "shape": {
            "fill_kinds": shape.get("fill_kinds") or {},
            "line_widths_pt": shape.get("line_widths_pt") or [],
            "corner_radius": shape.get("corner_radius") or {},
        },
        "layout": {
            "safe_area": layout.get("safe_area") or {},
            "per_kind": layout.get("per_kind") or {},
        },
        "spacing": {
            "dominant_horizontal": (spacing_graph or {}).get("global_dominant", {}).get("horizontal") or [],
            "dominant_vertical": (spacing_graph or {}).get("global_dominant", {}).get("vertical") or [],
        },
    }


def validate_design(
    design_dna: dict[str, Any],
    rules: dict[str, Any],
    *,
    size_tolerance_pt: float = 1.0,
    max_spacing_deviation_in: float = 0.15,
) -> list[dict[str, Any]]:
    """Check a candidate deck's design DNA against a rulebook.

    Findings carry ``code`` / ``detail`` / ``severity``; an empty list means
    the candidate respects every rule this version knows how to check.
    """
    from .spacing_graph import build_spacing_graph

    segment = design_dna.get("design_dna") or design_dna
    findings: list[dict[str, Any]] = []
    typography = (rules.get("typography") or {})
    allowed_sizes = [float(size) for size in typography.get("allowed_sizes_pt") or []]
    allowed_hex = {str(value).upper() for value in (rules.get("color") or {}).get("allowed_hex") or []}

    # R-TYPO-001: every text size must sit in the named scale (± tolerance)
    for entry in (segment.get("typography") or {}).get("size_census") or []:
        size = float(entry.get("size_pt") or 0)
        if allowed_sizes and not any(abs(size - allowed) <= size_tolerance_pt for allowed in allowed_sizes):
            findings.append({
                "code": "R-TYPO-001",
                "severity": "medium",
                "detail": f"font size {size}pt is outside the template type scale {allowed_sizes}",
            })

    # R-COLOR-001: filled rgb must be a named palette colour
    for entry in (segment.get("color") or {}).get("census") or []:
        rgb = str(entry.get("rgb") or "").upper()
        if rgb and allowed_hex and rgb not in allowed_hex:
            findings.append({
                "code": "R-COLOR-001",
                "severity": "medium",
                "detail": f"fill colour #{rgb} is not in the template palette",
            })

    # R-SPACING-001: dominant gaps should match the template rhythm
    template_h = {
        entry["gap_in"] for entry in ((rules.get("spacing") or {}).get("dominant_horizontal") or [])
    }
    if template_h:
        # one graph for the whole deck, indexed by slide (V2.2: was per-page rebuild)
        full_graph = build_spacing_graph(design_dna)
        per_page_gaps: dict[int, list[float]] = {}
        for page in design_dna.get("slides") or []:
            slide_no = int(page.get("slide") or 0)
            gaps = [entry["gap_in"] for entry in full_graph.get("per_page", {}).get(str(slide_no), {}).get("horizontal", [])]
            per_page_gaps[slide_no] = gaps
        for page in design_dna.get("slides") or []:
            slide_no = int(page.get("slide") or 0)
            for gap in per_page_gaps.get(slide_no, []):
                if not any(abs(gap - known) <= max_spacing_deviation_in for known in template_h):
                    findings.append({
                        "code": "R-SPACING-001",
                        "severity": "low",
                        "detail": f"page {slide_no}: horizontal gap {gap}in deviates from template rhythm {sorted(template_h)}",
                    })
    return findings
