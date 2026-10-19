from __future__ import annotations

import pytest

from ppt_agent.parsers import parse_markdown
from ppt_agent.storyboard import (
    StoryboardValidationError,
    normalize_storyboard,
    storyboard_to_plan,
)


SAMPLE = """# Service Review

## Current State

- 4 sites are live
- Adoption reached 82%

## Next Steps

- Expand the pilot to two departments
"""


def test_storyboard_preserves_order_sources_and_design_intent() -> None:
    document = parse_markdown(SAMPLE)
    by_text = {block.text: block.id for block in document.blocks if block.text}
    by_item = {
        item: block.id
        for block in document.blocks
        for item in block.items
    }
    headings = [block for block in document.blocks if block.type == "heading"]
    raw = {
        "schema": "storyboard/v1",
        "design_profile": {"visual_direction": "bright editorial, restrained"},
        "slides": [
            {
                "kind": "cover",
                "title": "Service Review",
                "source_block_ids": [headings[0].id],
            },
            {
                "kind": "content",
                "title": "Adoption is established",
                "key_message": "The rollout has reached most pilot sites.",
                "source_block_ids": [
                    headings[1].id,
                    by_item["4 sites are live"],
                    by_item["Adoption reached 82%"],
                ],
                "archetype": "metrics_row",
                "visual_form": "A compact metric comparison",
                "visual_kit": "quad_cards",
            },
            {
                "kind": "closing",
                "title": "Next decision",
                "source_block_ids": [
                    headings[2].id,
                    by_item["Expand the pilot to two departments"],
                ],
            },
        ],
    }

    storyboard = normalize_storyboard(raw, document, constraints={"max_pages": 3})
    plan = storyboard_to_plan(storyboard, document)

    assert plan["page_total"] == 3
    assert [page["title"] for page in plan["pages"]] == [
        "Service Review",
        "Adoption is established",
        "Next decision",
    ]
    assert plan["pages"][1]["source_blocks"] == [
        headings[1].id,
        by_item["4 sites are live"],
    ]
    assert plan["pages"][1]["archetype"]["archetype"] == "metrics_row"
    assert plan["pages"][1]["key_message"] == "The rollout has reached most pilot sites."
    assert plan["pages"][1]["visual_kit"] == "quad_cards"
    assert storyboard["design_profile"]["visual_direction"].startswith("bright editorial")


def test_storyboard_rejects_unknown_source_block_ids() -> None:
    document = parse_markdown(SAMPLE)
    raw = {
        "slides": [
            {"kind": "content", "title": "Unsupported", "source_block_ids": ["not-in-source"]},
        ],
    }

    with pytest.raises(StoryboardValidationError, match="unknown source block"):
        normalize_storyboard(raw, document)


def test_storyboard_rejects_pages_over_user_budget() -> None:
    document = parse_markdown(SAMPLE)
    raw = {
        "slides": [
            {"kind": "cover", "title": "Service Review", "source_block_ids": []},
            {"kind": "closing", "title": "Next decision", "source_block_ids": []},
        ],
    }

    with pytest.raises(StoryboardValidationError, match="max_pages"):
        normalize_storyboard(raw, document, constraints={"max_pages": 1})
