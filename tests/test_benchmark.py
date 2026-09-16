import json
from pathlib import Path

import pytest

from ppt_agent.benchmark import (
    BenchmarkReport,
    deck_signature,
    load_cases,
    run_benchmark,
    summarize,
    write_report,
)
from ppt_agent.contracts import BENCHMARK_SCHEMA_VERSION

# A slide with twelve bullets overflows the 7.5in slide, so the gate must fail.
OVERFLOWING_CASE = "# Over\n\n## Crowded\n\n" + "".join(
    f"- bullet number {index} with enough text to wrap\n" for index in range(1, 13)
)


def test_load_cases_is_sorted_and_filtered(cases_dir: Path):
    cases = load_cases(cases_dir)
    assert cases
    assert cases == sorted(cases)
    assert all(case.suffix == ".md" for case in cases)
    assert len(load_cases(cases_dir, "03_*.md")) == 1


def test_load_cases_rejects_a_missing_directory(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_cases(tmp_path / "nowhere")


def test_benchmark_passes_on_the_shipped_cases(cases_dir: Path, workspace: Path):
    pytest.importorskip("pptx")
    report = run_benchmark(cases_dir, workspace / "bench", pattern="03_*.md")
    assert report.passed is True
    assert report.deterministic is True
    assert len(report.cases) == 1
    case = report.cases[0]
    assert case.ok is True
    assert case.slides > 0
    assert case.gate_passed is True
    assert case.gate_mode in {"rendered", "structural"}
    assert case.ir_deterministic and case.pptx_deterministic and case.html_deterministic
    assert case.pptx_bytes > 0 and case.html_bytes > 0
    assert case.duration_ms >= 0
    assert "PASS" in summarize(report)


def test_benchmark_report_is_stable_json(cases_dir: Path, workspace: Path):
    pytest.importorskip("pptx")
    report = run_benchmark(cases_dir, workspace / "bench", pattern="03_*.md")
    payload = report.to_dict()
    assert payload["schema_version"] == BENCHMARK_SCHEMA_VERSION
    assert payload["passed"] is True
    assert payload["summary"]["cases"] == 1
    assert payload["summary"]["deterministic"] == 1
    assert "duration_ms" in payload["cases"][0]
    # Relative-only paths keep reports diffable across machines.
    assert payload["workspace"] == "."
    assert str(workspace).lower() not in json.dumps(payload).lower()

    target = write_report(report, workspace / "bench" / "report.json")
    assert json.loads(target.read_text(encoding="utf-8"))["passed"] is True


def test_benchmark_detects_a_deck_that_fails_the_gate(workspace: Path):
    pytest.importorskip("pptx")
    cases = workspace / "cases"
    cases.mkdir(parents=True, exist_ok=True)
    (cases / "overflow.md").write_text(OVERFLOWING_CASE, encoding="utf-8")

    report = run_benchmark(cases, workspace / "runs")
    assert report.passed is False
    case = report.cases[0]
    assert case.ok is False
    assert case.gate_passed is False
    assert case.gate_mode == "structural" or case.gate_mode == "rendered"
    assert any("outside slide bounds" in error for error in case.errors), case.errors


def test_benchmark_reports_a_plan_failure_instead_of_crashing(workspace: Path, monkeypatch):
    cases = workspace / "cases"
    cases.mkdir(parents=True, exist_ok=True)
    (cases / "broken.md").write_text("# Broken\n", encoding="utf-8")

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic planner failure")

    monkeypatch.setattr("ppt_agent.benchmark.architect_markdown_to_ir", boom)
    report = run_benchmark(cases, workspace / "runs")
    assert report.passed is False
    assert "synthetic planner failure" in report.cases[0].errors[0]


def test_deck_signature_ignores_packaging_timestamps(tmp_path: Path):
    pptx = pytest.importorskip("pptx")
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_textbox(100000, 100000, 2000000, 500000).text_frame.text = "hello"
    first = tmp_path / "a.pptx"
    second = tmp_path / "b.pptx"
    prs.save(str(first))
    prs.save(str(second))
    assert deck_signature(first) == deck_signature(second)


def test_empty_case_directory_fails_the_run(workspace: Path):
    cases = workspace / "cases"
    cases.mkdir(parents=True, exist_ok=True)
    report = run_benchmark(cases, workspace / "runs")
    assert isinstance(report, BenchmarkReport)
    assert report.passed is False
    assert report.cases == []
    assert "FAIL" in summarize(report)
