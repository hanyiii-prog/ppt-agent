"""Semantic role labelling tests."""

from __future__ import annotations

import pytest

from ppt_agent.semantic_role import (
    SEMANTIC_ROLES,
    annotate_deck_dna,
    infer_semantic_role,
)


@pytest.fixture(scope="module")
def annotated(tmp_path_factory: pytest.TempPathFactory) -> dict:
    from tests.design_dna_fixtures import build_template_pptx, load_annotated_dna

    path = build_template_pptx(tmp_path_factory.mktemp("semantic") / "template.pptx")
    return load_annotated_dna(path)


def test_role_vocabulary_is_fixed() -> None:
    assert "title" in SEMANTIC_ROLES and "decoration" in SEMANTIC_ROLES


def test_placeholder_and_name_rules() -> None:
    assert infer_semantic_role({"placeholder": {"type": "TITLE"}}) == "title"
    assert infer_semantic_role({"placeholder": {"type": "SLIDE_NUMBER"}}) == "page_number"
    assert infer_semantic_role({"name": "Logo.png", "element": "pic"}) == "logo"
    assert infer_semantic_role({"name": "logo-mark", "element": "sp"}) == "logo"


def test_element_kind_rules() -> None:
    assert infer_semantic_role({"element": "pic"}) == "image"
    assert infer_semantic_role({"element": "graphicFrame"}) == "table"
    assert infer_semantic_role({"element": "grpSp", "is_group": True}) == "group"


def test_text_and_geometry_rules() -> None:
    big = {"element": "sp", "text": {"text": "标题", "fonts": [{"size_pt": 24}]}}
    assert infer_semantic_role(big, page_kind="cover") == "title"
    body = {"element": "sp", "text": {"text": "要点", "fonts": [{"size_pt": 16}]}}
    assert infer_semantic_role(body, page_kind="content") == "body"
    tiny = {"element": "sp", "text": {"text": "", "fonts": []},
            "geometry": {"left": 1, "top": 1, "width": 0.2, "height": 0.2}}
    assert infer_semantic_role(tiny, slide_area=100.0) == "decoration"
    wash = {"element": "sp", "geometry": {"left": 0, "top": 0, "width": 13, "height": 7}}
    assert infer_semantic_role(wash, slide_area=97.5) == "decoration"


def test_annotate_deck_dna_tags_every_layer(annotated: dict) -> None:
    assert annotated["schema"] == "template-dna/v0.4"
    for page in annotated["slides"]:
        for layer in page["layers"]:
            assert layer.get("semantic_role") in SEMANTIC_ROLES
    for master in annotated["masters"]:
        for shape in master["shapes"]:
            assert shape.get("semantic_role") in SEMANTIC_ROLES
    # the repeated logo block on content pages is recognised
    content_roles = {
        layer.get("semantic_role")
        for page in annotated["slides"] if page["kind"] == "content"
        for layer in page["layers"]
    }
    assert "logo" in content_roles
    assert "title" in content_roles


def test_annotate_is_non_destructive() -> None:
    original = {"slides": [{"kind": "cover", "layers": [{"element": "pic"}]}]}
    result = annotate_deck_dna(original)
    assert "semantic_role" not in original["slides"][0]["layers"][0]
    assert result["slides"][0]["layers"][0]["semantic_role"] == "image"
