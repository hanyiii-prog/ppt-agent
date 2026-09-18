"""CLI + MCP surface tests for the fidelity engine."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fidelity_fixtures import build_rich_pptx, mutate_pptx

from ppt_agent.cli import main
from ppt_agent.mcp.tools import ToolContext, call_tool, tool_names
from ppt_agent.sdk import PptAgent


def _run_cli(argv: list[str]) -> int:
    old = sys.argv
    try:
        sys.argv = ["ppt-agent", *argv]
        return main()
    finally:
        sys.argv = old


def _context(tmp_path: Path) -> ToolContext:
    return ToolContext(agent=PptAgent(), workspace=tmp_path)


def test_cli_fidelity_extract_writes_dna(tmp_path: Path):
    source = build_rich_pptx(tmp_path / "ref.pptx")
    out = tmp_path / "dna.json"
    assert _run_cli(["fidelity", "extract", str(source), "--slide", "2", "-o", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["page_kind"] == "toc"
    assert payload["toc"]["item_count"] == 3
    assert payload["schema"] == "template-dna/fidelity/v2"


def test_cli_fidelity_diff_reports_codes(tmp_path: Path):
    reference = build_rich_pptx(tmp_path / "ref.pptx")
    candidate = mutate_pptx(reference, tmp_path / "cand.pptx", "rotation_changed")
    out = tmp_path / "diff.json"
    code = _run_cli(["fidelity", "diff", str(reference), str(candidate), "--slide", "3", "-o", str(out)])
    assert code == 2
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["codes"].get("geometry.rotation")


def test_cli_fidelity_audit_gate(tmp_path: Path):
    reference = build_rich_pptx(tmp_path / "ref.pptx")
    candidate = mutate_pptx(reference, tmp_path / "cand.pptx", "geometry_changed")
    out = tmp_path / "gate.json"
    assert _run_cli(["fidelity", "audit", str(reference), str(reference), "-o", str(out)]) == 0
    assert _run_cli(["fidelity", "audit", str(reference), str(candidate), "-o", str(out)]) == 2
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["passed"] is False


def test_cli_fidelity_repair_loop(tmp_path: Path):
    reference = build_rich_pptx(tmp_path / "ref.pptx")
    candidate = mutate_pptx(reference, tmp_path / "cand.pptx", "rotation_changed")
    out = tmp_path / "repaired.pptx"
    code = _run_cli(["fidelity", "repair", str(reference), str(candidate),
                     "-o", str(out), "--workspace", str(tmp_path / "work")])
    assert code == 0
    assert out.exists()


def test_cli_fidelity_validate_structural_only(tmp_path: Path):
    reference = build_rich_pptx(tmp_path / "ref.pptx")
    candidate = mutate_pptx(reference, tmp_path / "cand.pptx", "geometry_changed")
    out = tmp_path / "validation.json"
    code = _run_cli(["fidelity", "validate", str(reference), str(candidate),
                     "--no-render", "-o", str(out)])
    assert code == 2
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert payload["visual"]["status"] == "skipped"


def test_cli_fidelity_validate_passes_for_identical_decks(tmp_path: Path):
    reference = build_rich_pptx(tmp_path / "ref.pptx")
    out = tmp_path / "validation.json"
    assert _run_cli(["fidelity", "validate", str(reference), str(reference), "--no-render",
                     "-o", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["passed"] is True


def test_mcp_tool_names_include_fidelity():
    names = tool_names()
    for name in ("ppt_agent_fidelity_extract", "ppt_agent_fidelity_diff",
                 "ppt_agent_fidelity_repair", "ppt_agent_fidelity_validate"):
        assert name in names


def _unwrap(result: dict) -> dict:
    """call_tool wraps payloads in an MCP content envelope."""
    assert result.get("isError") in (False, None), result
    return json.loads(result["content"][0]["text"])


def test_mcp_fidelity_tools_round_trip(tmp_path: Path):
    reference = build_rich_pptx(tmp_path / "ref.pptx")
    candidate = mutate_pptx(reference, tmp_path / "cand.pptx", "rotation_changed")
    context = _context(tmp_path)

    extracted = _unwrap(call_tool("ppt_agent_fidelity_extract", {"source": str(reference), "slide": 3}, context))
    assert extracted["page_kind"] == "content"

    diff = _unwrap(call_tool("ppt_agent_fidelity_diff", {"reference": str(reference), "candidate": str(candidate), "slide": 3}, context))
    assert diff["passed"] is False
    assert diff["codes"].get("geometry.rotation")

    repaired = _unwrap(call_tool("ppt_agent_fidelity_repair", {
        "reference": str(reference), "candidate": str(candidate), "output": "repaired.pptx",
    }, context))
    assert repaired["passed"] is True
    assert (tmp_path / "repaired.pptx").exists()

    validated = _unwrap(call_tool("ppt_agent_fidelity_validate", {
        "reference": str(reference), "candidate": str(tmp_path / "repaired.pptx"),
        "render": False,
    }, context))
    assert validated["passed"] is True
