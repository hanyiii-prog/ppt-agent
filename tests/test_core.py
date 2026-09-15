import json

from ppt_agent.markdown import parse_markdown
from ppt_agent.qa import validate_ir


def test_markdown_to_ir_preserves_provenance():
    presentation = parse_markdown("# Demo\n\n## Intro\n\n- A\n- B")
    assert presentation.title == "Demo"
    assert len(presentation.slides) == 1
    assert len(presentation.slides[0].components) == 2
    assert presentation.slides[0].components[0].provenance[0].locator == "L5"


def test_qa_rejects_missing_slide_purpose():
    report = validate_ir({"version": "0.1", "metadata": {}, "slides": [{"id": "x"}]})
    assert not report.passed
    assert any(finding.rule == "schema" for finding in report.findings)


def test_json_roundtrip():
    presentation = parse_markdown("# Demo\n## One\ntext")
    data = json.loads(presentation.to_json())
    assert data["metadata"]["title"] == "Demo"
    assert data["slides"][0]["components"][0]["text"] == "text"


def test_qa_rejects_negative_geometry_and_duplicate_slide_ids():
    report = validate_ir(
        {
            "version": "0.1",
            "metadata": {"title": "x"},
            "slides": [
                {"id": "same", "purpose": "a", "components": [{"type": "text", "id": "c", "w": -1}]},
                {"id": "same", "purpose": "b", "components": []},
            ],
        }
    )
    assert not report.passed
    assert any(finding.rule == "geometry" for finding in report.findings)
    assert any(finding.rule == "identity" for finding in report.findings)
