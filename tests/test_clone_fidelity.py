# -*- coding: utf-8 -*-
"""Clone route x Fidelity Engine: chrome inheritance gate end-to-end."""
import pytest

pytest.importorskip("pptx")

from pptx import Presentation  # noqa: E402

from ppt_agent.clone_build import (  # noqa: E402
    chrome_fidelity_gate,
    render_clone_deck,
)

from tests.test_clone_build import _plan, mini_template  # noqa: E402,F401

# The clone route keeps the TEMPLATE's page order. mini_template shells are
# [cover, cover, section, content x4]; the plan maps onto them as:
#   plan page 1 (cover)    -> template shell 1 -> output page 1
#   plan page 2 (toc)      -> template shell 4 (content pool) -> output page 4
#   plan page 3 (section)  -> template shell 3 -> output page 3
#   plan pages 4-6 content -> template shells 5-7 -> output pages 5-7
#   plan page 7 (closing)  -> template shell 2 (second cover) -> output page 2
OUTPUT_KINDS = ["cover", "content", "section", "toc", "content", "content", "closing"]


def test_render_clone_deck_passes_its_own_gate(mini_template, tmp_path):
    """A faithful clone build must pass the chrome fidelity gate."""
    out = tmp_path / "deck.pptx"
    result = render_clone_deck(mini_template, _plan(), out, audit=True, fidelity=True)
    gate = result["fidelity"]
    assert gate["schema"] == "template-dna/chrome-fidelity-gate/v1"
    assert gate["passed"] is True, gate["issues"][:5]
    assert gate["issue_count"] == 0
    kinds = [page["page_kind"] for page in gate["pages"]]
    assert kinds == OUTPUT_KINDS
    # the TOC page (output page 4) kept its structural fingerprint
    toc_page = gate["pages"][3]
    assert toc_page["page_kind"] == "toc"


def test_gate_detects_clobbered_layout_chrome(mini_template, tmp_path):
    out = tmp_path / "deck.pptx"
    render_clone_deck(mini_template, _plan(), out, audit=False, fidelity=False)

    # LayoutShapes has no add_shape: inject a real <p:sp> via raw XML instead
    from lxml import etree

    prs = Presentation(str(out))
    for layout in prs.slide_layouts:
        if layout.name == "内容页 - 有标题":
            sp_xml = (
                '<p:sp xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                '<p:nvSpPr><p:cNvPr id="4001" name="Clobber"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
                '<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1828800" cy="1828800"/></a:xfrm>'
                '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
                '<a:solidFill><a:srgbClr val="FF0000"/></a:solidFill></p:spPr>'
                '<p:txBody><a:bodyPr/><a:p/></p:txBody></p:sp>'
            )
            layout.shapes._spTree.append(etree.fromstring(sp_xml))
            break
    tampered = tmp_path / "tampered.pptx"
    prs.save(str(tampered))

    gate = chrome_fidelity_gate(mini_template, tampered)
    assert gate["passed"] is False
    codes = {issue["code"] for issue in gate["issues"]}
    assert any(code.startswith("layer.") or code.startswith("inheritance.") for code in codes)
    # every output page served by the tampered layout must be flagged
    flagged = {page["slide_index"] for page in gate["pages"] if not page["passed"]}
    assert {4, 5, 6, 7} <= flagged


def test_gate_flags_page_kind_divergence(mini_template, tmp_path):
    out = tmp_path / "deck.pptx"
    render_clone_deck(mini_template, _plan(), out, audit=False, fidelity=False)
    gate = chrome_fidelity_gate(mini_template, out, expected_kinds={4: "content"})
    assert gate["passed"] is False
    mismatch = next(i for i in gate["issues"] if i["code"] == "page.page_kind")
    assert mismatch["reference"] == "content"
    assert mismatch["candidate"] == "toc"


def test_gate_accepts_correct_anchors(mini_template, tmp_path):
    out = tmp_path / "deck.pptx"
    render_clone_deck(mini_template, _plan(), out, audit=False, fidelity=False)
    gate = chrome_fidelity_gate(mini_template, out, expected_kinds={3: "section", 4: "toc"})
    assert gate["passed"] is True, gate["issues"][:3]


def test_gate_reports_visual_status_when_rendering(mini_template, tmp_path):
    out = tmp_path / "deck.pptx"
    result = render_clone_deck(mini_template, _plan(), out, audit=False, fidelity=True, render=True)
    visual = result["fidelity"].get("visual")
    assert visual is not None
    assert visual["status"] in ("visual_pass", "visual_fail", "renderer_unavailable", "renderer_error")
    # a renderer problem must never be reported as a pass
    if visual["status"] in ("renderer_unavailable", "renderer_error"):
        assert visual["passed"] is False
