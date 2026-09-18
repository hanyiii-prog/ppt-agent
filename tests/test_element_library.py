"""Element library + component library tests on a real mini template."""

from __future__ import annotations

import pytest

from ppt_agent.component_library import build_component_library
from ppt_agent.element_library import SCHEMA as LIB_SCHEMA
from ppt_agent.element_library import build_element_library, element_signature


@pytest.fixture(scope="module")
def deck(tmp_path_factory: pytest.TempPathFactory) -> dict:
    from tests.design_dna_fixtures import build_template_pptx, load_annotated_dna

    path = build_template_pptx(tmp_path_factory.mktemp("elements") / "template.pptx")
    return load_annotated_dna(path)


def test_signature_is_name_free_and_stable() -> None:
    a = {"element": "sp", "geometry": {"prst_geom": {"type": "rect"}, "width": 1.0, "height": 0.5},
         "style": {"fill": {"type": "solid", "rgb": "11506E"}, "line": {}}}
    b = {"element": "sp", "name": "other-name", "geometry": {"prst_geom": {"type": "rect"}, "width": 1.0, "height": 0.5},
         "style": {"fill": {"type": "solid", "rgb": "11506E"}, "line": {}}}
    c = {**a, "style": {"fill": {"type": "solid", "rgb": "FFFFFF"}, "line": {}}}
    assert element_signature(a) == element_signature(b)
    assert element_signature(a) != element_signature(c)


def test_repeated_bar_and_logo_are_found(deck: dict) -> None:
    library = build_element_library(deck)
    assert library["schema"] == LIB_SCHEMA
    assert library["recurring_elements"] >= 2
    names = {entry["name"] for entry in library["elements"]}
    assert "header-bar" in names and "logo-block" in names
    bar = next(entry for entry in library["elements"] if entry["name"] == "header-bar")
    assert bar["occurrences"] == 4  # every slide carries the bar
    assert 0.0 < bar["reuse_score"] <= 1.0


def test_unique_elements_are_excluded_by_default(deck: dict) -> None:
    library = build_element_library(deck)
    # "谢谢" (closing) and the two distinct body textboxes occur once
    singles = [entry for entry in library["elements"] if entry["occurrences"] < 2]
    assert singles == []
    everything = build_element_library(deck, min_occurrences=1)
    assert len(everything["elements"]) >= len(library["elements"])


def test_bar_plus_logo_form_a_component(deck: dict) -> None:
    components = build_component_library(deck)
    assert components["schema"] == "component-library/v1"
    assert components["components"], "bar+logo co-occur on all four pages"
    top = components["components"][0]
    assert top["member_count"] >= 2
    assert len(top["pages"]) >= 2
    roles = {member.get("semantic_role") for member in top["members"]}
    assert "logo" in roles
