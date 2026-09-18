"""Design rulebook build + validate tests."""

from __future__ import annotations

import pytest

from ppt_agent.design_dna import build_design_dna
from ppt_agent.design_rules import build_design_rules, validate_design
from ppt_agent.spacing_graph import build_spacing_graph


@pytest.fixture(scope="module")
def template_deck(tmp_path_factory: pytest.TempPathFactory) -> dict:
    from tests.design_dna_fixtures import build_template_pptx, load_annotated_dna

    path = build_template_pptx(tmp_path_factory.mktemp("rules-template") / "template.pptx")
    return load_annotated_dna(path)


@pytest.fixture(scope="module")
def rulebook(template_deck: dict) -> dict:
    design = build_design_dna(template_deck)
    return build_design_rules(design, build_spacing_graph(design))


def test_rulebook_carries_checkable_sections(rulebook: dict) -> None:
    assert rulebook["schema"] == "design-rules/v1"
    assert rulebook["typography"]["allowed_sizes_pt"], "named scale sizes must be listed"
    assert "11506E" in rulebook["color"]["allowed_hex"], "primary blue must be in the palette"
    assert rulebook["spacing"]["dominant_horizontal"] or rulebook["spacing"]["dominant_vertical"]


def test_compliant_candidate_produces_no_findings(
    template_deck: dict, rulebook: dict
) -> None:
    assert validate_design(build_design_dna(template_deck), rulebook) == []


def test_rogue_size_and_colour_are_flagged(template_deck: dict, rulebook: dict) -> None:
    candidate = build_design_dna(template_deck)
    segment = candidate["design_dna"]
    # inject a rogue size and a rogue colour into the census
    segment["typography"]["size_census"] = [
        {"size_pt": 37.0, "count": 2},
        *segment["typography"]["size_census"],
    ]
    segment["color"]["census"] = [{"rgb": "FF00FF", "count": 3}, *segment["color"]["census"]]
    findings = validate_design(candidate, rulebook)
    codes = {finding["code"] for finding in findings}
    assert "R-TYPO-001" in codes
    assert "R-COLOR-001" in codes
    assert all(finding["detail"] for finding in findings), "findings must be explicit"


def test_own_rhythm_produces_no_spacing_findings(
    template_deck: dict, rulebook: dict
) -> None:
    findings = validate_design(build_design_dna(template_deck), rulebook)
    assert not [finding for finding in findings if finding["code"] == "R-SPACING-001"]
