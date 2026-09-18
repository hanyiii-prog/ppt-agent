"""Fidelity Mode resolution + gate report tests."""

from __future__ import annotations

import pytest

from ppt_agent.fidelity_mode import MODES, gates_report, resolve_fidelity_mode

DNA = {"schema": "template-dna/v0.4", "slides": [{"slide": 1, "kind": "cover"}]}


def test_mode_vocabulary() -> None:
    assert set(MODES) == {"clone", "designed"}


def test_mode_inferred_from_template_presence() -> None:
    assert resolve_fidelity_mode(template_dna=DNA)["mode"] == "clone"
    assert resolve_fidelity_mode(template_dna=None)["mode"] == "designed"
    assert resolve_fidelity_mode()["mode"] == "designed"


def test_mode_explicit_request_wins() -> None:
    report = resolve_fidelity_mode("designed", template_dna=DNA)
    assert report["mode"] == "designed"
    assert "explicitly requested" in report["basis"]


def test_clone_mode_requires_dna() -> None:
    report = resolve_fidelity_mode("clone", template_dna=None)
    assert report["mode"] is None
    assert "requires template DNA" in report["error"]


def test_unknown_mode_is_rejected() -> None:
    report = resolve_fidelity_mode("yolo")
    assert report["mode"] is None and report["error"]
    with pytest.raises(ValueError):
        gates_report("yolo")


def test_clone_gates_obligations() -> None:
    report = gates_report("clone", has_rasterizer=True)
    gates = {gate["name"]: gate for gate in report["gates"]}
    assert gates["chrome_fidelity_gate"]["status"] == "required"
    assert gates["toc_fingerprint"]["status"] == "required"
    assert gates["page_audit"]["status"] == "required"
    assert gates["design_rules_validation"]["status"] == "off"
    assert gates["visual_regression"]["status"] == "required"


def test_designed_gates_obligations() -> None:
    gates = {gate["name"]: gate for gate in gates_report("designed", has_design_rules=True)["gates"]}
    assert gates["design_rules_validation"]["status"] == "required"
    assert gates["chrome_fidelity_gate"]["status"] == "off"
    assert gates["page_audit"]["status"] == "required"


def test_designed_without_rulebook_degrades_explicitly() -> None:
    report = gates_report("designed", has_design_rules=False)
    gates = {gate["name"]: gate for gate in report["gates"]}
    assert gates["design_rules_validation"]["status"] == "degraded"
    assert gates["design_rules_validation"]["reason"], "degradation must carry a reason"


def test_missing_rasterizer_degrades_visual_gate() -> None:
    gates = {gate["name"]: gate for gate in gates_report("clone", has_rasterizer=False)["gates"]}
    assert gates["visual_regression"]["status"] == "degraded"
    assert "structural" in gates["visual_regression"]["reason"]


def test_gate_summary_counts_add_up() -> None:
    report = gates_report("designed", has_design_rules=True, has_rasterizer=True)
    summary = report["summary"]
    assert summary["required"] + summary["recommended"] + summary["degraded"] + summary["off"] == len(report["gates"])
