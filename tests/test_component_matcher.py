"""Component Matcher tests: real fixture library + synthetic count-fit cases."""

from __future__ import annotations

import pytest

from ppt_agent.component_matcher import SCHEMA, match_components
from ppt_agent.component_library import build_component_library
from ppt_agent.content_ir import ContentBlock, ContentDocument
from ppt_agent.parsers import parse_markdown


@pytest.fixture(scope="module")
def fixture_library(tmp_path_factory: pytest.TempPathFactory) -> dict:
    from tests.design_dna_fixtures import build_template_pptx, load_annotated_dna

    path = build_template_pptx(tmp_path_factory.mktemp("matcher") / "template.pptx")
    deck = load_annotated_dna(path)
    return build_component_library(deck)


DOCUMENT = """# 上线总结

## 项目概况

- 覆盖 5 个院区

## 四项举措

- 完成数据治理工作
- 完成接口联调工作
- 完成全院培训工作
- 完成应急演练工作
"""


def test_chrome_component_auto_matches_every_page(fixture_library: dict) -> None:
    result = match_components(fixture_library, parse_markdown(DOCUMENT))
    assert result["schema"] == SCHEMA
    assert result["metadata"]["llm"] == "off"
    chrome = [match for match in result["matches"] if match["priority"] == "P1-chrome"]
    assert chrome, "the bar+logo component must auto-match as chrome"
    top = chrome[0]
    assert top["scope"] == "every-page"
    assert "logo" in top["roles"]
    assert top["reasons"], "chrome matches must state their reason"


def test_count_fit_matches_four_item_section() -> None:
    library = {
        "components": [
            {
                "component_id": "comp-1",
                "member_count": 4,
                "pages": [2, 3],
                "page_coverage": 0.5,
                "reuse_score": 0.5,
                "members": [
                    {"key": f"card-{i}", "name": f"card{i}", "element": "sp",
                     "semantic_role": "card", "geometry": None}
                    for i in range(4)
                ],
            }
        ]
    }
    result = match_components(library, parse_markdown(DOCUMENT))
    matches = result["matches"]
    assert matches and matches[0]["priority"] == "P2/P3-content"
    hit = matches[0]["hits"][0]
    assert hit["section"] == "四项举措"
    assert "P2-count" in hit["priorities"]
    assert hit["score"] >= 0.7


def test_unmatched_components_are_reported_honestly(fixture_library: dict, ) -> None:
    document = parse_markdown("# 只有标题\n\n## 项目概况\n\n- 覆盖 5 个院区\n")
    result = match_components(fixture_library, document)
    # every component lands somewhere explicit: matched or unmatched, never dropped
    total = result["component_count"]
    assert total == len(result["matches"]) + len(result["unmatched"])


def test_synthetic_three_card_component_stays_honest_on_two_item_section() -> None:
    library = {
        "components": [
            {
                "component_id": "comp-9",
                "member_count": 3,
                "pages": [1, 2],
                "page_coverage": 0.5,
                "reuse_score": 0.5,
                "members": [
                    {"key": f"card-{i}", "name": f"card{i}", "element": "sp",
                     "semantic_role": "card", "geometry": None}
                    for i in range(3)
                ],
            }
        ]
    }
    document = ContentDocument(blocks=[
        ContentBlock(type="heading", id="h-1", text="概况", level=2),
        ContentBlock(type="bullets", id="b-1", items=["只有一条", "第二条"]),
    ])
    result = match_components(library, document)
    assert not result["matches"]
    assert result["unmatched"] and result["unmatched"][0]["component_id"] == "comp-9"
