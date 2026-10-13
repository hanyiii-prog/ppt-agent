from __future__ import annotations

import json

from ppt_agent.parsers import parse_markdown
from ppt_agent.storyboard import repair_storyboard_plan


def _plan(document):
    content = next(block for block in document.blocks if block.type == "bullets")
    heading = next(block for block in document.blocks if block.type == "heading" and block.level == 2)
    return {
        "pages": [
            {
                "page_no": 1,
                "kind": "cover",
                "title": "Report",
                "source_blocks": [],
            },
            {
                "page_no": 2,
                "kind": "content",
                "title": "Results",
                "source_blocks": [heading.id, content.id],
                "key_message": "Revenue reached 91%.",
                "layout_variant": "standard",
                "visual_form": "two balanced cards",
                "archetype": {
                    "schema": "archetype/v1",
                    "archetype": "cards_grid",
                    "confidence": 0.8,
                    "reason": "parallel evidence",
                },
            },
        ],
        "page_total": 2,
    }


def test_repair_changes_composition_without_changing_source_or_copy() -> None:
    document = parse_markdown(
        "# Report\n\n## Results\n\n- Revenue reached 91%\n- Retention reached 72%"
    )
    plan = _plan(document)
    original = json.loads(json.dumps(plan))

    repaired, report = repair_storyboard_plan(
        plan,
        document,
        [{"page": 2, "kind": "visual_critic", "severity": "error",
          "rule": "dense_content", "message": "内容拥挤"}],
        lambda _prompt: json.dumps({
            "schema": "storyboard-repair/v1",
            "repairs": [{
                "page_no": 2,
                "archetype": "narrative",
                "layout_variant": "wide",
                "visual_form": "wide evidence rows",
            }],
        }),
    )

    old_page, new_page = original["pages"][1], repaired["pages"][1]
    assert new_page["source_blocks"] == old_page["source_blocks"]
    assert new_page["title"] == old_page["title"]
    assert new_page["key_message"] == old_page["key_message"]
    assert new_page["archetype"]["archetype"] == "narrative"
    assert new_page["layout_variant"] == "wide"
    assert report["applied_pages"] == [2]


def test_repair_rejects_unknown_pages_archetypes_and_content_edits() -> None:
    document = parse_markdown("# Report\n\n## Results\n\n- Revenue reached 91%")
    plan = _plan(document)
    original = json.loads(json.dumps(plan))

    repaired, report = repair_storyboard_plan(
        plan,
        document,
        [{"page": 2, "kind": "page_gate", "issues": ["overlap"]}],
        lambda _prompt: json.dumps({
            "schema": "storyboard-repair/v1",
            "repairs": [
                {"page_no": 99, "archetype": "narrative", "layout_variant": "wide"},
                {"page_no": 2, "archetype": "invented", "layout_variant": "wide"},
                {"page_no": 2, "title": "New unsupported claim",
                 "archetype": "narrative", "layout_variant": "wide"},
            ],
        }),
    )

    assert repaired == original
    assert report["applied_pages"] == []
    assert report["rejected_count"] == 4


def test_repair_skips_pages_without_blocking_findings() -> None:
    document = parse_markdown("# Report\n\n## Results\n\n- Revenue reached 91%")
    plan = _plan(document)
    calls = []

    repaired, report = repair_storyboard_plan(
        plan,
        document,
        [{"page": 2, "kind": "visual_critic", "severity": "warning",
          "message": "可优化"}],
        lambda prompt: calls.append(prompt) or "{}",
    )

    assert repaired == plan
    assert not calls
    assert report["stop_reason"] == "no_blocking_findings"
