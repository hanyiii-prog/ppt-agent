"""TOC regression fixtures (md §17): five TOC layouts, nine verification points."""
from pathlib import Path

from pptx import Presentation

from ppt_agent.fidelity import extract_fidelity_dna
from ppt_agent.fidelity_diff import compare_dna
from ppt_agent.fidelity_gate import compare_decks
from ppt_agent.fidelity_model import build_deck_fidelity
from ppt_agent.fidelity_repair_executor import execute_repair_plan
from ppt_agent.fidelity_repair import repair_plan_dict
from ppt_agent.visual_regression import visual_status

from tests.fidelity_fixtures import build_toc_pptx


TOC_VARIANTS = {
    "toc-single-column": dict(columns=1, numbered=False),
    "toc-multi-column": dict(columns=2, numbered=False),
    "toc-numbered": dict(columns=1, numbered=True),
    "toc-hierarchical": dict(columns=1, numbered=True, hierarchical=True),
    "toc-with-indicator": dict(columns=1, numbered=True, indicator=True),
}


def _dna(path: Path) -> dict:
    return extract_fidelity_dna(path, slide_index=1)


def test_every_toc_variant_is_stable_identified_as_toc(tmp_path: Path):
    fingerprints = {}
    for name, kwargs in TOC_VARIANTS.items():
        path = build_toc_pptx(tmp_path / f"{name}.pptx", **kwargs)
        dna = _dna(path)
        assert dna["page_kind"] == "toc", name
        toc = dna["toc"]
        assert toc and toc["structure_fingerprint"], name
        assert toc["item_count"] == 4, name
        fingerprints[name] = toc["structure_fingerprint"]
    # every variant has a distinct structure fingerprint: TOC DNA is not a
    # relabelled content page
    assert len(set(fingerprints.values())) == len(TOC_VARIANTS)


def test_toc_numbering_and_indentation_are_extractable(tmp_path: Path):
    numbered = _dna(build_toc_pptx(tmp_path / "n.pptx", numbered=True))
    numbers = [item["numbering"] for item in numbered["toc"]["items"]]
    assert numbers == [1, 2, 3, 4]
    assert numbered["toc"]["numbering"] == "arabic"
    assert numbered["toc"]["numbering_ordered"] is True

    hierarchical = _dna(build_toc_pptx(tmp_path / "h.pptx", hierarchical=True))
    ys = [item["geometry_emu"]["x"] for item in hierarchical["toc"]["items"]]
    # level-1 entries are indented relative to level-0 entries
    assert ys[1] > ys[0] and ys[3] > ys[2]

    unnumbered = _dna(build_toc_pptx(tmp_path / "u.pptx", numbered=False))
    assert all(item["numbering"] is None for item in unnumbered["toc"]["items"])
    assert unnumbered["toc"]["numbering"] == "none"

    with_indicator = _dna(build_toc_pptx(tmp_path / "i.pptx", indicator=True))
    assert with_indicator["toc"]["indicator_count"] == 4


def test_toc_items_carry_geometry_for_alignment_checks(tmp_path: Path):
    path = build_toc_pptx(tmp_path / "g.pptx", columns=2)
    deck = build_deck_fidelity(path)
    toc = deck.slides[0].toc
    assert toc["item_count"] == 4
    xs = [item["geometry_emu"]["x"] for item in toc["items"]]
    # two columns: entries 0,1 share a column, entries 2,3 share the next
    assert abs(xs[0] - xs[1]) < 1000 or abs(xs[2] - xs[3]) < 1000


def test_toc_passes_structural_and_visual_gates(tmp_path: Path):
    path = build_toc_pptx(tmp_path / "t.pptx", numbered=True)
    gate = compare_decks(path, path)
    assert gate["passed"]
    report = compare_dna(_dna(path), _dna(path))
    assert report.passed and report.issue_count == 0

    status = visual_status(path, path, tmp_path / "visual")
    assert status["status"] == "visual_pass"
    assert status["passed"] is True


def test_toc_repair_restores_entries_without_touching_other_kinds(tmp_path: Path):
    reference = build_toc_pptx(tmp_path / "ref.pptx", numbered=True, indicator=True)
    reference_dna = _dna(reference)
    fingerprint = reference_dna["toc"]["structure_fingerprint"]

    # shift the second TOC entry down: a geometry.position defect on a TOC page
    prs = Presentation(str(reference))
    shapes = list(prs.slides[0].shapes)
    entry = shapes[2]  # title textbox, then entry textboxes
    entry.top = entry.top + 100000
    candidate = tmp_path / "cand.pptx"
    prs.save(str(candidate))

    report = compare_dna(reference_dna, _dna(candidate))
    assert not report.passed
    assert report.codes.get("geometry.position")

    plan = repair_plan_dict(report)
    result = execute_repair_plan(candidate, plan, tmp_path / "repaired.pptx", slide_index=1)
    assert result["applied"]

    gate = compare_decks(reference, result["output"])
    assert gate["passed"], [page["issues"] for page in gate["pages"] if not page["passed"]]
    # TOC structure fingerprint survived the repair untouched
    repaired_dna = _dna(result["output"])
    assert repaired_dna["page_kind"] == "toc"
    assert repaired_dna["toc"]["structure_fingerprint"] == fingerprint
