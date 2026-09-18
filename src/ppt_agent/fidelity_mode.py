"""Fidelity Mode: which generation route, and which gates MUST run.

Why this exists
---------------
The engine now has two production routes with different gate obligations:

``clone``     a template deck drives the output byte-for-byte; the clone
              chrome gate, the six-kind page audit and the TOC fingerprint
              are *mandatory* -- a clone that lost the template chrome is a
              failure even if it looks fine.
``designed``  theme-driven generation from scratch; the design-rules
              validation and the page audit are mandatory, the chrome gate
              is not applicable (there is no chrome to inherit).

The mode is resolved up front and every gate's status is *explicit*:
``required`` (must pass), ``degraded`` (runs a weaker version, with reason)
or ``off`` (not applicable, with reason). Red line 4: gates are never
silently skipped -- this module is where that promise is machine-checked.
"""

from __future__ import annotations

from typing import Any

SCHEMA = "fidelity-mode/v1"

MODES: tuple[str, ...] = ("clone", "designed")


def resolve_fidelity_mode(
    requested: str | None = None,
    *,
    template_dna: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the effective mode.

    ``requested`` wins when valid; otherwise a template DNA payload implies
    ``clone`` and its absence implies ``designed``. The report always states
    how the decision was made.
    """
    has_dna = isinstance(template_dna, dict) and bool(template_dna.get("slides"))
    if requested is None:
        mode = "clone" if has_dna else "designed"
        basis = "inferred from template presence"
    elif requested in MODES:
        mode = requested
        basis = "explicitly requested"
        if mode == "designed" and has_dna:
            basis = "explicitly requested (template DNA present but ignored by design)"
        if mode == "clone" and not has_dna:
            return {
                "schema": SCHEMA,
                "mode": None,
                "basis": basis,
                "error": "clone mode requires template DNA; none provided",
            }
    else:
        return {
            "schema": SCHEMA,
            "mode": None,
            "basis": "invalid request",
            "error": f"unknown fidelity mode {requested!r}; use {list(MODES)}",
        }
    return {"schema": SCHEMA, "mode": mode, "basis": basis}


def gates_report(
    mode: str,
    *,
    has_design_rules: bool = False,
    has_rasterizer: bool = False,
) -> dict[str, Any]:
    """Enumerate the gates a mode owes, each explicitly required/degraded/off."""
    if mode not in MODES:
        raise ValueError(f"unknown fidelity mode {mode!r}; use {list(MODES)}")

    gates: list[dict[str, Any]] = [
        {
            "name": "page_audit",
            "status": "required",
            "reason": "overflow/collision/empty/duplicate/doubling/stale_placeholder checks",
        }
    ]

    if mode == "clone":
        gates.append({
            "name": "chrome_fidelity_gate",
            "status": "required",
            "reason": "a clone must inherit the template's layout/master chrome verbatim",
        })
        gates.append({
            "name": "toc_fingerprint",
            "status": "required",
            "reason": "the TOC structure fingerprint must survive the whole chain",
        })
        gates.append({
            "name": "design_rules_validation",
            "status": "off",
            "reason": "clone route inherits the template, it does not re-theme",
        })
    else:
        if has_design_rules:
            gates.append({
                "name": "design_rules_validation",
                "status": "required",
                "reason": "designed output must respect the template rulebook (R-TYPO/R-COLOR/R-SPACING)",
            })
        else:
            gates.append({
                "name": "design_rules_validation",
                "status": "degraded",
                "reason": "no rulebook provided: only the page audit protects consistency",
            })
        gates.append({
            "name": "chrome_fidelity_gate",
            "status": "off",
            "reason": "designed output has no template chrome to inherit",
        })

    if has_rasterizer:
        gates.append({
            "name": "visual_regression",
            "status": "required" if mode == "clone" else "recommended",
            "reason": "rasteriser available: rendered comparison runs",
        })
    else:
        gates.append({
            "name": "visual_regression",
            "status": "degraded",
            "reason": "no rasteriser: visual review degrades to structural geometry checks",
        })

    return {
        "schema": SCHEMA,
        "mode": mode,
        "gates": gates,
        "summary": {
            "required": sum(1 for gate in gates if gate["status"] == "required"),
            "recommended": sum(1 for gate in gates if gate["status"] == "recommended"),
            "degraded": sum(1 for gate in gates if gate["status"] == "degraded"),
            "off": sum(1 for gate in gates if gate["status"] == "off"),
        },
    }
