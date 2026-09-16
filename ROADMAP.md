# PPT Agent Roadmap

Status legend: `[x]` shipped in code, `[~]` partial / v1 scope, `[ ]` not started.

## V0.1 — Foundation
- [x] GitHub repository
- [x] Portable Skill contract
- [x] Universal Presentation IR schema (`ir/presentation.schema.json`)
- [x] Typed Python IR models (`ppt_agent.ir`, with `to_dict`/`from_dict` round trip)
- [x] Initial CLI
- [x] GitHub Actions test workflow
- [x] PPTX inspection baseline (`ppt_agent.template.analyze_pptx`)
- [x] First end-to-end sample (`tests/test_render_e2e.py`)

## V0.2 — Template DNA
- [x] reference PPTX structural extraction
- [x] typography/color/spacing inventory
- [x] page-type clustering (first/body/last roles)
- [x] reusable layout grammar (`ppt_agent.visual_grammar`)
- [x] OOXML fidelity capture (alpha / z-order / group / raw XML)
- [x] DNA → IR conversion (`ppt_agent.dna_to_ir`)

## V0.3 — Build + Visual QA
- [x] native editable PPTX renderer (`ppt_agent.renderer`)
- [x] deterministic rendering (single code path, no randomness)
- [x] geometry checks (`ppt_agent.page_validation`)
- [x] contact-sheet visual review (`ppt_agent.visual_regression`, `visual_critic`)
- [x] `ir-to-pptx` CLI command

## V0.4 — Evidence Safety
- [x] Fact Registry (`ppt_agent.fact_registry`)
- [x] provenance graph (claims carry `Provenance`)
- [~] Fact Lock (support audit via `audit_presentation`)
- [~] source-to-slide traceability

## V0.5 — Critic + Repair
- [x] visual critic (`ppt_agent.visual_critic`)
- [x] layout/density scoring (`ppt_agent.visual_critic`, `visual_grammar`)
- [x] targeted repair tasks (`delivery._repair_requests`)
- [x] bounded rebuild loop (`delivery.run_repair_loop`)
- [x] renderer build callback (`renderer.make_ir_build`)

## V0.6 — Story + Agent Interoperability
- [x] Story Architect (`ppt_agent.story`)
- [ ] MCP server
- [ ] generic adapter
- [ ] capability negotiation

## V0.7 — Host Adapters
- [ ] Codex
- [ ] WorkBuddy
- [ ] 豆包工作
- [ ] additional agent hosts

## V1.0 — Stable Platform
- [ ] stable IR contract
- [ ] renderer SDK
- [ ] adapter SDK
- [ ] benchmark suite
- [ ] reproducible release process

## Renderer v1 scope

The native renderer (`src/ppt_agent/renderer.py`) consumes Universal IR and emits an editable `.pptx`:

- Absolute placement when a component carries `x/y/w/h` (inches); deterministic top-down flow otherwise.
- Component types: `text`, `paragraph`, `title`, `shape`, `image`, `table`, `chart`, `group`.
- Style mapping: solid fill + transparency (OOXML `a:alpha`), line color/width, font size/bold/italic/name/color/alignment.
- Slide background fill, speaker notes, per-deck slide size from `theme.slide_size_inches`.
- Group components recursively render their captured children.

Known v1 limits (tracked for V1.0): gradient fills fall back to solid, chart components render as labelled placeholders, embedded image bytes require `data.bytes`/`data.path`.
