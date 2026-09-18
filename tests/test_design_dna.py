"""Design DNA (``template-dna/v1.0``) tests.

Locks: the v1.0 stamp, v0.4 key preservation, and the named
shape / layout / typography / colour segments derived from real PPTX.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ppt_agent.contracts import (
    SUPPORTED_TEMPLATE_DNA_VERSIONS,
    check_template_dna_version,
    is_template_dna_compatible,
)
from ppt_agent.design_dna import SCHEMA as DESIGN_DNA_SCHEMA
from ppt_agent.design_dna import build_design_dna
from tests.design_dna_fixtures import load_annotated_dna


@pytest.fixture(scope="module")
def deck(tmp_path_factory: pytest.TempPathFactory) -> dict:
    from tests.design_dna_fixtures import build_template_pptx

    path = build_template_pptx(tmp_path_factory.mktemp("design-dna") / "template.pptx")
    return load_annotated_dna(path)


def test_v1_is_superset_of_v04(deck: dict) -> None:
    upgraded = build_design_dna(deck)
    assert upgraded["schema"] == "template-dna/v1.0"
    for key in ("slides", "masters", "page_kinds", "theme", "dominant_palette",
                "global_style_statistics", "presentation", "special_surfaces"):
        assert key in upgraded, f"v0.4 key {key} lost in v1.0"
    # original untouched
    assert deck["schema"] == "template-dna/v0.4"


def test_shape_segment_names_the_language(deck: dict) -> None:
    design = build_design_dna(deck)["design_dna"]
    shape = design["shape"]
    assert shape["fill_kinds"].get("solid", 0) >= 5
    assert shape["borders"], "border census must classify with/without borders"
    assert isinstance(shape["corner_radius"]["census"], list)


def test_layout_segment_finds_content_margins(deck: dict) -> None:
    design = build_design_dna(deck)["design_dna"]
    content = design["layout"]["per_kind"].get("content") or {}
    margins = content.get("margins") or {}
    # the fixture content pages start at x=0.9 (bar is full-bleed and excluded)
    assert abs(margins.get("left_in", 99) - 0.9) < 0.1
    assert margins.get("content_boxes", 0) >= 2
    assert design["layout"]["safe_area"], "safe area must be derived"


def test_typography_scale_is_named_and_ordered(deck: dict) -> None:
    design = build_design_dna(deck)["design_dna"]
    scale = design["typography"]["scale_named"]
    present = [value for value in scale.values() if isinstance(value, (int, float))]
    assert present, "named scale must pick sizes"
    assert max(present) >= 24.0, "display/title level must capture the big sizes"
    assert design["typography"]["families"], "font families must be listed"


def test_color_segment_names_primary_and_text(deck: dict) -> None:
    design = build_design_dna(deck)["design_dna"]
    named = design["color"]["named"]
    assert named["primary"] == "11506E", "dominant filled blue must be primary"
    assert named["text"], "text colour must resolve"


def test_version_contract_accepts_both_dialects(deck: dict) -> None:
    assert ("0.4", "1.0") == tuple(SUPPORTED_TEMPLATE_DNA_VERSIONS)
    assert check_template_dna_version(deck) == "0.4"
    upgraded = build_design_dna(deck)
    assert check_template_dna_version(upgraded) == "1.0"
    assert is_template_dna_compatible(upgraded)
    with pytest.raises(Exception):
        check_template_dna_version({"schema": "template-dna/v9.9"})


def test_design_dna_schema_constant() -> None:
    assert DESIGN_DNA_SCHEMA == "template-dna/v1.0"
