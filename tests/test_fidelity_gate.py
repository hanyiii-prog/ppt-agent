from ppt_agent.fidelity_diff import compare_dna, normalize_dna
from ppt_agent.fidelity_gate import compare_decks


def test_normalize_dna_ignores_package_local_identifiers():
    a = {"source": "/tmp/a.pptx", "slide": {"path": "ppt/slides/slide1.xml", "relationship_id": "rId7", "geometry": {"x": 10}}}
    b = {"source": "/tmp/b.pptx", "slide": {"path": "ppt/slides/slide9.xml", "relationship_id": "rId3", "geometry": {"x": 10}}}
    assert normalize_dna(a) == normalize_dna(b)
    assert compare_dna(a, b).passed


def test_fidelity_keeps_alpha_rotation_and_z_order_significant():
    base = {"schema": "template-dna/fidelity/v1", "slide": {"shapes": [
        {"z_index": 0, "geometry": {"rotation": 0, "x": 10}, "style": {"alpha": 50000}},
        {"z_index": 1, "geometry": {"rotation": 0, "x": 20}, "style": {"alpha": 100000}},
    ]}}
    changed = {"schema": "template-dna/fidelity/v1", "slide": {"shapes": [
        {"z_index": 1, "geometry": {"rotation": 180, "x": 10}, "style": {"alpha": 60000}},
        {"z_index": 0, "geometry": {"rotation": 0, "x": 20}, "style": {"alpha": 100000}},
    ]}}
    report = compare_dna(base, changed)
    assert not report.passed
    assert report.summary["geometry"] >= 1
    assert report.summary["style"] >= 1
    assert report.summary["layer_order"] >= 1


def test_deck_gate_rejects_different_slide_packages(tmp_path):
    # A PPTX is required by the extractor; this test only verifies the public
    # contract's input boundary without silently accepting non-PPTX data.
    bad = tmp_path / "not-a-pptx.pptx"
    bad.write_bytes(b"not a zip")
    try:
        compare_decks(bad, bad)
    except Exception as exc:
        assert isinstance(exc, (ValueError, OSError, EOFError, RuntimeError))
    else:
        raise AssertionError("invalid PPTX must not pass the fidelity gate")
