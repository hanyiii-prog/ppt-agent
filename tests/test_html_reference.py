from __future__ import annotations

from ppt_agent.html_reference import extract_html_reference


def test_html_reference_extracts_titles_and_diagram_text_without_executing_scripts(
    tmp_path,
) -> None:
    source = tmp_path / "reference.html"
    source.write_text(
        """
        <!doctype html><html><head><title>Architecture reference</title>
        <style>.secret { display: none }</style></head><body>
        <h1>Phase One</h1>
        <section class="architecture-diagram">
          <h2>Data flow</h2><div>EMR to data hub to specialty registry</div>
        </section>
        <script>ignore this executable content</script>
        </body></html>
        """,
        encoding="utf-8",
    )

    report = extract_html_reference(source)

    assert report["title"] == "Architecture reference"
    assert "Phase One" in report["headings"]
    assert "Data flow" in report["headings"]
    assert "EMR to data hub to specialty registry" in report["diagram_excerpt"]
    assert "ignore this executable content" not in report["text_excerpt"]
    assert ".secret" not in report["text_excerpt"]


def test_html_reference_clips_large_text_and_reports_truncation(tmp_path) -> None:
    source = tmp_path / "long.html"
    source.write_text("<p>" + ("architecture " * 2000) + "</p>", encoding="utf-8")

    report = extract_html_reference(source, max_chars=800)

    assert len(report["text_excerpt"]) <= 800
    assert report["truncated"] is True
