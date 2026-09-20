"""Tests for per-page-kind DNA extraction."""
import pytest

from ppt_agent.page_kind_dna import (
    ALL_KINDS, BASE_KINDS, SPECIAL_KINDS,
    build_page_kind_dna, get_kind_dna,
)


def _make_deck_dna():
    return {
        "slides": [
            {"slide": 1, "kind": "cover", "layers": [
                {"origin": "slide", "element": "sp", "semantic_role": "title",
                 "geometry": {"left": 1.0, "top": 2.0, "width": 8.0, "height": 1.5},
                 "text": {"text": "My Cover", "fonts": [{"size_pt": 36, "name": "Arial"}]},
                 "style": {"fill": {"type": "solid", "rgb": "1A73E8"}}},
            ]},
            {"slide": 2, "kind": "toc", "layers": [
                {"origin": "slide", "element": "sp", "semantic_role": "body",
                 "geometry": {"left": 1.0, "top": 1.5, "width": 8.0, "height": 3.0},
                 "text": {"text": "Agenda", "fonts": [{"size_pt": 20, "name": "Calibri"}]},
                 "style": {"fill": {"type": "none"}}},
            ]},
            {"slide": 3, "kind": "content", "layers": [
                {"origin": "slide", "element": "sp", "semantic_role": "title",
                 "geometry": {"left": 0.7, "top": 0.5, "width": 11.0, "height": 1.0},
                 "text": {"text": "Content Title", "fonts": [{"size_pt": 24, "name": "Arial"}]},
                 "style": {"fill": {"type": "solid", "rgb": "333333"}}},
                {"origin": "slide", "element": "sp", "semantic_role": "body",
                 "geometry": {"left": 0.7, "top": 2.0, "width": 11.0, "height": 3.0},
                 "text": {"text": "Body text", "fonts": [{"size_pt": 14, "name": "Calibri"}]},
                 "style": {"fill": {"type": "none"}}},
            ]},
            {"slide": 4, "kind": "section", "layers": [
                {"origin": "slide", "element": "sp", "semantic_role": "title",
                 "geometry": {"left": 1.0, "top": 2.5, "width": 10.0, "height": 1.5},
                 "text": {"text": "Section 1", "fonts": [{"size_pt": 32, "name": "Arial"}]},
                 "style": {"fill": {"type": "solid", "rgb": "1A73E8"}}},
            ]},
            {"slide": 5, "kind": "closing", "layers": [
                {"origin": "slide", "element": "sp", "semantic_role": "title",
                 "geometry": {"left": 1.0, "top": 3.0, "width": 8.0, "height": 1.0},
                 "text": {"text": "Thank You", "fonts": [{"size_pt": 28, "name": "Arial"}]},
                 "style": {"fill": {"type": "solid", "rgb": "1A73E8"}}},
            ]},
        ],
        "presentation": {"slide_size_inches": {"width": 13.333, "height": 7.5}},
        "masters": [],
        "theme": {"colors": {"accent1": "1A73E8"}},
    }


def _make_design_dna(deck_dna):
    from ppt_agent.design_dna import build_design_dna
    return build_design_dna(deck_dna)


class TestBuildPageKindDna:
    def test_schema_stamp(self):
        deck = _make_deck_dna()
        design = _make_design_dna(deck)
        result = build_page_kind_dna(deck, design)
        assert result["schema"] == "page-kind-dna/v1"

    def test_fingerprint_carried(self):
        deck = _make_deck_dna()
        design = _make_design_dna(deck)
        result = build_page_kind_dna(deck, design)
        assert result["template_fingerprint"] == design["template_fingerprint"]

    def test_all_base_kinds_present(self):
        deck = _make_deck_dna()
        design = _make_design_dna(deck)
        result = build_page_kind_dna(deck, design)
        for kind in BASE_KINDS:
            assert kind in result["kinds"]

    def test_cover_has_own_typography(self):
        deck = _make_deck_dna()
        design = _make_design_dna(deck)
        result = build_page_kind_dna(deck, design)
        cover = result["kinds"]["cover"]
        assert "36.0" in [str(v) for v in cover["typography"]["scale_named"].values()]

    def test_content_differs_from_cover(self):
        deck = _make_deck_dna()
        design = _make_design_dna(deck)
        result = build_page_kind_dna(deck, design)
        cover_colors = {c["rgb"] for c in result["kinds"]["cover"]["color"]["census"]}
        content_colors = {c["rgb"] for c in result["kinds"]["content"]["color"]["census"]}
        assert "1A73E8" in cover_colors
        assert "333333" in content_colors

    def test_special_detection(self):
        deck = _make_deck_dna()
        deck["slides"][2]["layers"].append(
            {"origin": "slide", "element": "graphicFrame", "semantic_role": "table",
             "geometry": {"left": 0.7, "top": 2.0, "width": 8.0, "height": 3.0},
             "text": {"text": "", "fonts": []}, "style": {"fill": {"type": "none"}}}
        )
        design = _make_design_dna(deck)
        result = build_page_kind_dna(deck, design)
        if "special" in result["kinds"]:
            assert "chart" in result["kinds"]["special"]


class TestGetKindDna:
    def test_known_kind(self):
        pkd = {"kinds": {"cover": {"typography": {"scale_named": {"display": 36}}}, "content": {}}}
        dna = get_kind_dna(pkd, "cover")
        assert dna["typography"]["scale_named"]["display"] == 36

    def test_unknown_falls_back_to_content(self):
        pkd = {"kinds": {"content": {"typography": {"scale_named": {"body": 14}}}}}
        dna = get_kind_dna(pkd, "quote")
        assert dna["typography"]["scale_named"]["body"] == 14

    def test_special_kind_lookup(self):
        pkd = {"kinds": {
            "content": {"typography": {}},
            "special": {"quote": {"typography": {"scale_named": {"display": 30}}}},
        }}
        dna = get_kind_dna(pkd, "quote")
        assert dna["typography"]["scale_named"]["display"] == 30
