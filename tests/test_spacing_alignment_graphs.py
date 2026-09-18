"""Spacing graph + alignment graph tests."""

from __future__ import annotations

import pytest

from ppt_agent.alignment_graph import build_alignment_graph, page_alignment
from ppt_agent.spacing_graph import build_spacing_graph, page_spacing


def test_page_spacing_finds_horizontal_gap() -> None:
    # three boxes in a row -> two identical 1.0in gaps -> dominant needs count>=2
    records = [
        {"geometry": {"left": 1.0, "top": 1.0, "width": 2.0, "height": 1.0}},
        {"geometry": {"left": 4.0, "top": 1.0, "width": 2.0, "height": 1.0}},
        {"geometry": {"left": 7.0, "top": 1.0, "width": 2.0, "height": 1.0}},
    ]
    spacing = page_spacing(records)
    assert spacing["horizontal_gaps"] >= 2
    assert spacing["dominant_horizontal"][0]["gap_in"] == pytest.approx(1.0)


def test_page_spacing_ignores_overlapping_boxes() -> None:
    records = [
        {"geometry": {"left": 1.0, "top": 1.0, "width": 2.0, "height": 1.0}},
        {"geometry": {"left": 1.5, "top": 1.2, "width": 2.0, "height": 1.0}},
    ]
    spacing = page_spacing(records)
    assert spacing["horizontal_gaps"] == 0
    assert spacing["vertical_gaps"] == 0


def test_page_alignment_clusters_shared_edges() -> None:
    records = [
        {"geometry": {"left": 0.9, "top": 0.5, "width": 3.0, "height": 0.8}},
        {"geometry": {"left": 0.92, "top": 1.9, "width": 3.0, "height": 2.0}},
        {"geometry": {"left": 5.0, "top": 2.5, "width": 2.0, "height": 1.0}},
    ]
    axes = page_alignment(records)
    assert axes["left"] and axes["left"][0]["count"] == 2
    assert pytest.approx(axes["left"][0]["at_in"], abs=0.01) == 0.91


def test_deck_level_graphs_over_fixture_deck(tmp_path_factory: pytest.TempPathFactory) -> None:
    from tests.design_dna_fixtures import build_template_pptx, load_annotated_dna

    path = build_template_pptx(tmp_path_factory.mktemp("graphs") / "template.pptx")
    deck = load_annotated_dna(path)

    spacing = build_spacing_graph(deck)
    assert spacing["schema"] == "spacing-graph/v1"
    assert spacing["global_dominant"]["horizontal"], "repeated 0.9in title alignment yields gaps"

    alignment = build_alignment_graph(deck)
    assert alignment["schema"] == "alignment-graph/v1"
    content = alignment["per_kind"].get("content") or {}
    left_axis = (content.get("axes") or {}).get("left") or []
    assert left_axis and left_axis[0]["count"] >= 2, "content titles/bodies share the left edge"
