"""Canonical Fidelity Model tests: real PPTX → DeckFidelity tree."""
from pathlib import Path

from ppt_agent.fidelity_model import build_deck_fidelity, build_slide_fidelity

from tests.fidelity_fixtures import build_rich_pptx


def test_deck_model_covers_every_slide(tmp_path: Path):
    path = build_rich_pptx(tmp_path / "rich.pptx")
    deck = build_deck_fidelity(path)
    assert len(deck.slides) == 4
    assert deck.presentation["slide_count"] == 4
    assert [slide.page_kind for slide in deck.slides] == ["cover", "toc", "content", "closing"]
    payload = deck.to_dict()
    assert payload["schema"] == deck.schema_version
    assert len(payload["slides"]) == 4


def test_slide_model_layers_are_globally_ordered_and_sourced(tmp_path: Path):
    path = build_rich_pptx(tmp_path / "rich.pptx")
    deck = build_deck_fidelity(path)
    slide = deck.slides[2]  # content page
    assert slide.rendered_layers, "content page must carry layers"
    orders = [layer.render_order for layer in slide.rendered_layers]
    assert orders == sorted(orders), "rendered_layers must follow global render order"
    sources = {layer.source for layer in slide.rendered_layers}
    assert sources <= {"master", "layout", "slide"}
    # the injected layout band must appear as an inherited layer
    assert any(layer.source == "layout" and layer.name == "LayoutBand" for layer in slide.inherited_layers)
    assert all(layer.source == "slide" for layer in slide.local_layers)


def test_element_model_carries_full_evidence(tmp_path: Path):
    path = build_rich_pptx(tmp_path / "rich.pptx")
    deck = build_deck_fidelity(path)
    slide = deck.slides[2]

    picture = next(layer for layer in slide.rendered_layers if layer.kind == "pic")
    assert picture.media["sha256"]
    assert picture.crop == {"l": 25000}
    assert picture.raw_ooxml_evidence["raw_xml"]

    connector = next(layer for layer in slide.rendered_layers if layer.kind == "cxnSp")
    assert connector.connector["end_arrow"]["type"] == "arrow"

    custom = next(layer for layer in slide.rendered_layers if layer.custom_geometry)
    assert custom.custom_geometry["paths"]

    table = next(layer for layer in slide.rendered_layers if layer.table)
    assert table.table["rows"]

    rotated = next(
        layer for layer in slide.rendered_layers
        if layer.geometry and layer.geometry["rotation"] == 90.0 and layer.source == "slide"
    )
    assert rotated.geometry["rendered_bbox"]["cy"] > rotated.geometry["rendered_bbox"]["cx"]

    group = next(layer for layer in slide.rendered_layers if layer.kind == "grpSp")
    assert group.children and group.children[0].parent == group.element_id


def test_background_resolution_and_toc(tmp_path: Path):
    path = build_rich_pptx(tmp_path / "rich.pptx")
    deck = build_deck_fidelity(path)
    toc_slide = deck.slides[1]
    assert toc_slide.page_kind == "toc"
    assert toc_slide.toc["item_count"] == 3
    payload = toc_slide.to_dict()
    assert "rendered_layers" in payload and "inherited_layers" in payload and "local_layers" in payload


def test_build_slide_fidelity_is_pure_function_of_dna(tmp_path: Path):
    from ppt_agent.fidelity import extract_fidelity_dna

    path = build_rich_pptx(tmp_path / "rich.pptx")
    dna = extract_fidelity_dna(path, slide_index=2)
    model = build_slide_fidelity(dna)
    rebuilt = build_slide_fidelity(dna)
    assert model.to_dict() == rebuilt.to_dict(), "model construction must be deterministic"
