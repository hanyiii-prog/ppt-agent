# Benchmark Cases

Markdown fixtures that the reproducible benchmark suite renders, gates and checks for determinism.

```bash
ppt-agent benchmark benchmarks/cases -o dist/benchmark-report.json
```

Every case is rendered **twice**. A case passes only when all of the following hold:

1. the IR is byte-identical across both runs,
2. the two PPTX decks have an identical shape tree (byte comparison is meaningless — PPTX embeds
   packaging timestamps, so `benchmark.deck_signature()` compares type, geometry and text instead),
3. the two HTML decks are byte-identical,
4. every page passes the delivery gate.

## Cases

| File | Profile |
|---|---|
| `01_project_review.md` | Full project review: 8 slides, mixed cover/body/closing roles, numbered and bulleted content |
| `02_kpi_review.md` | Metric-heavy review: 7 slides, many numeric claims for the fact lock |
| `03_specialty_db.md` | Short scoped deck: 5 slides, field-by-field decision language |

## Reading the report

```json
{
  "schema_version": "1.0",
  "workspace": ".",
  "rasteriser": false,
  "gate_mode": "structural",
  "passed": true,
  "deterministic": true,
  "summary": {"cases": 3, "passed": 3, "failed": 0, "deterministic": 3, "pages": 20},
  "cases": [
    {
      "name": "01_project_review.md",
      "ok": true,
      "slides": 8,
      "gate_passed": true,
      "gate_mode": "structural",
      "pptx_bytes": 48321,
      "deterministic": {"ir": true, "pptx": true, "html": true},
      "duration_ms": 336,
      "errors": []
    }
  ]
}
```

Paths are relative to the workspace and no machine-specific detail is recorded, so reports from
different hosts are directly comparable.

## The suite can fail

A benchmark that only ever passes proves nothing. `tests/test_benchmark.py` builds a case with twelve
bullets on one slide — enough to push a flow-layout component past the bottom of a 7.5in slide — and
asserts that the run fails with an `outside slide bounds` finding. The same test also verifies that a
planner crash is reported per case instead of aborting the whole run.

## Adding a case

Create a `.md` file here. `#` is the deck title and every `##` starts a slide. Keep it representative:
cover, body and closing roles, at least one slide with four or more bullets, and real prose rather than
`lorem ipsum` — the layout estimator responds to text length, so synthetic filler hides real problems.
