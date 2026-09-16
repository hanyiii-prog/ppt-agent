"""Reproducible benchmark suite.

Measures the properties that actually matter for a build pipeline: does the
same input produce the same artifact, does every page pass the gate, and how
long does a deck take. Paths in the report are relative to the workspace so two
runs on different machines can be diffed.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contracts import BENCHMARK_SCHEMA_VERSION
from .renderers import render_with
from .sdk import PptAgent
from .story import architect_markdown_to_ir

DEFAULT_CASE_GLOB = "*.md"


@dataclass
class CaseResult:
    name: str
    ok: bool
    slides: int
    gate_passed: bool
    gate_mode: str
    pptx_bytes: int = 0
    html_bytes: int = 0
    ir_deterministic: bool = False
    pptx_deterministic: bool = False
    html_deterministic: bool = False
    duration_ms: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "slides": self.slides,
            "gate_passed": self.gate_passed,
            "gate_mode": self.gate_mode,
            "pptx_bytes": self.pptx_bytes,
            "html_bytes": self.html_bytes,
            "deterministic": {
                "ir": self.ir_deterministic,
                "pptx": self.pptx_deterministic,
                "html": self.html_deterministic,
            },
            "duration_ms": self.duration_ms,
            "errors": list(self.errors),
        }


@dataclass
class BenchmarkReport:
    cases: list[CaseResult]
    workspace: str
    rasteriser: bool
    gate_mode: str
    total_ms: int

    @property
    def passed(self) -> bool:
        return bool(self.cases) and all(case.ok for case in self.cases)

    @property
    def deterministic(self) -> bool:
        return all(
            case.ir_deterministic and case.pptx_deterministic and case.html_deterministic
            for case in self.cases
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BENCHMARK_SCHEMA_VERSION,
            "workspace": self.workspace,
            "rasteriser": self.rasteriser,
            "gate_mode": self.gate_mode,
            "passed": self.passed,
            "deterministic": self.deterministic,
            "total_ms": self.total_ms,
            "mean_ms": int(self.total_ms / len(self.cases)) if self.cases else 0,
            "summary": {
                "cases": len(self.cases),
                "passed": sum(1 for case in self.cases if case.ok),
                "failed": sum(1 for case in self.cases if not case.ok),
                "deterministic": sum(
                    1
                    for case in self.cases
                    if case.ir_deterministic and case.pptx_deterministic and case.html_deterministic
                ),
                "pages": sum(case.slides for case in self.cases),
            },
            "cases": [case.to_dict() for case in self.cases],
        }


def load_cases(cases_dir: str | Path, pattern: str = DEFAULT_CASE_GLOB) -> list[Path]:
    directory = Path(cases_dir)
    if not directory.exists():
        raise FileNotFoundError(f"benchmark cases directory not found: {directory}")
    return sorted(path for path in directory.glob(pattern) if path.is_file())


def deck_signature(pptx: str | Path) -> str:
    """Canonical structural signature of a deck.

    PPTX files embed timestamps, so byte comparison can never prove
    determinism. Compare the shape tree instead: type, geometry and text.
    """
    from pptx import Presentation

    prs = Presentation(str(pptx))
    slides: list[dict[str, Any]] = []
    for slide in prs.slides:
        shapes: list[list[Any]] = []
        for shape in slide.shapes:
            text = shape.text_frame.text if getattr(shape, "has_text_frame", False) else ""
            shapes.append([
                int(shape.shape_id),
                str(shape.shape_type),
                int(shape.left or 0),
                int(shape.top or 0),
                int(shape.width or 0),
                int(shape.height or 0),
                text,
            ])
        slides.append({
            "shapes": shapes,
            "size": [int(prs.slide_width or 0), int(prs.slide_height or 0)],
        })
    return json.dumps(slides, ensure_ascii=False, sort_keys=False)


def run_benchmark(
    cases_dir: str | Path,
    workspace: str | Path,
    *,
    agent: PptAgent | None = None,
    pattern: str = DEFAULT_CASE_GLOB,
) -> BenchmarkReport:
    """Render every case twice and compare artifacts, gates and timings."""
    from .visual_regression import rasteriser_available

    agent = agent or PptAgent()
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    cases = load_cases(cases_dir, pattern)
    results: list[CaseResult] = []
    started = time.perf_counter()

    for case in cases:
        case_started = time.perf_counter()
        errors: list[str] = []
        markdown = case.read_text(encoding="utf-8")
        case_dir = root / case.stem
        first = case_dir / "run-1"
        second = case_dir / "run-2"
        first.mkdir(parents=True, exist_ok=True)
        second.mkdir(parents=True, exist_ok=True)

        try:
            presentation = architect_markdown_to_ir(markdown, title=case.stem)
            ir_first = presentation.to_json()
            ir_second = architect_markdown_to_ir(markdown, title=case.stem).to_json()
        except Exception as exc:  # noqa: BLE001 - reported per case
            results.append(CaseResult(
                name=case.name, ok=False, slides=0, gate_passed=False,
                gate_mode="n/a", errors=[f"plan failed: {type(exc).__name__}: {exc}"],
                duration_ms=int((time.perf_counter() - case_started) * 1000),
            ))
            continue

        ir_deterministic = ir_first == ir_second

        pptx_first = pptx_second = None
        try:
            pptx_first = render_with(presentation, first / f"{case.stem}.pptx")
            pptx_second = render_with(presentation, second / f"{case.stem}.pptx")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"native render failed: {type(exc).__name__}: {exc}")

        html_first = html_second = None
        try:
            html_first = render_with(presentation, first / f"{case.stem}.html", renderer="html")
            html_second = render_with(presentation, second / f"{case.stem}.html", renderer="html")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"html render failed: {type(exc).__name__}: {exc}")

        pptx_deterministic = bool(
            pptx_first and pptx_second
            and deck_signature(pptx_first.path) == deck_signature(pptx_second.path)
        )
        html_deterministic = bool(
            html_first and html_second
            and Path(html_first.path).read_text(encoding="utf-8")
            == Path(html_second.path).read_text(encoding="utf-8")
        )

        gate_passed = False
        gate_mode = "n/a"
        if pptx_first is not None:
            gate = agent.gate(pptx_first.path, workspace=case_dir / "qa")
            gate_passed = bool(gate["passed"])
            gate_mode = str(gate["mode"])
            for page in (gate.get("page_gate") or {}).get("pages", []):
                if not page.get("passed"):
                    errors.append(f"page {page['page']}: {'; '.join(page.get('issues') or [])}")

        ok = (
            not errors
            and pptx_first is not None
            and html_first is not None
            and gate_passed
            and ir_deterministic
            and pptx_deterministic
            and html_deterministic
        )
        results.append(CaseResult(
            name=case.name,
            ok=ok,
            slides=len(presentation.slides),
            gate_passed=gate_passed,
            gate_mode=gate_mode,
            pptx_bytes=Path(pptx_first.path).stat().st_size if pptx_first else 0,
            html_bytes=Path(html_first.path).stat().st_size if html_first else 0,
            ir_deterministic=ir_deterministic,
            pptx_deterministic=pptx_deterministic,
            html_deterministic=html_deterministic,
            duration_ms=int((time.perf_counter() - case_started) * 1000),
            errors=errors,
        ))

    return BenchmarkReport(
        cases=results,
        workspace=".",
        rasteriser=rasteriser_available(),
        gate_mode=results[0].gate_mode if results else "n/a",
        total_ms=int((time.perf_counter() - started) * 1000),
    )


def write_report(report: BenchmarkReport, path: str | Path) -> Path:
    from .textio import write_json_lf

    return write_json_lf(path, report.to_dict())


def summarize(report: BenchmarkReport) -> str:
    lines = [
        f"benchmark: {'PASS' if report.passed else 'FAIL'} "
        f"({len(report.cases)} cases, {sum(c.slides for c in report.cases)} pages, "
        f"{report.total_ms} ms, gate={report.gate_mode})"
    ]
    for case in report.cases:
        marks = "".join(
            "D" if flag else "-"
            for flag in (case.ir_deterministic, case.pptx_deterministic, case.html_deterministic)
        )
        lines.append(
            f"  {'PASS' if case.ok else 'FAIL'} {case.name} slides={case.slides} "
            f"determinism={marks} {case.duration_ms}ms"
        )
        for error in case.errors:
            lines.append(f"       {error}")
    return "\n".join(lines)
