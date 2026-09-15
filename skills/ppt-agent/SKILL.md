# PPT Agent Skill

## Mission

Use PPT Agent as the presentation-engineering layer for an AI agent. The host agent supplies task context and model reasoning; PPT Agent owns source analysis, presentation planning, deterministic build, quality gates and repair.

## Required workflow

1. **Inspect** source documents and reference PPTX files before proposing slides.
2. **Extract evidence** and preserve provenance for important numbers, dates and claims.
3. **Define the story**: audience, objective, key message, evidence and slide purposes.
4. **Create Universal Presentation IR** as the source of truth.
5. **Analyze/apply Template DNA** when a reference deck is supplied.
6. **Build deterministically** with a supported renderer.
7. **Render the complete deck** before delivery. Never validate only a sample page.
8. **Run a per-page production gate** on every slide: render success, page count, dimensions, bounds/overflow, zero-size or broken elements, near-blank detection, readability/density checks, and visual consistency.
9. **Run visual fidelity regression** whenever a reference deck or known-good baseline exists. Compare **every page**, not only representative pages. A single failed page blocks delivery.
10. **Repair the source/IR/rules**, rebuild, rerender and recheck the whole deck. Repeat until every page passes or the task is explicitly stopped. Do not hide defects with untracked final-file patches.
11. **Deliver** only the validated presentation and its manifest/evidence artifacts when requested.

The production loop is therefore:

`Plan → Build → Render all pages → Page Gates → Visual Critic → Repair → Rebuild → Render all pages → Page Gates → Final Delivery`

This same loop is used both for development/regression testing and for the final user-facing PPT generation. Development tests prove the machinery works; production validation proves the actual requested deck is acceptable.

## Template DNA requirements

Template DNA is not a statistics report. It must preserve enough information to explain and reproduce the visual system.

At minimum, capture when present:

- element geometry, rotation and flips
- fill, line, alpha/transparency, gradients and effects
- typography and text-frame inheritance
- z-order and group parent/child relationships
- placeholders and their layout/master inheritance
- slide background, theme and color scheme
- slide master and slide-layout properties
- image relationships, crop/source rectangles and asset checksums
- custom geometry / freeform paths and connector definitions
- special surface roles such as **first**, **body**, **chapter**, and **last**

Use the OOXML fidelity layer as an escape hatch when `python-pptx` or another high-level library cannot represent a property exactly.

## Non-negotiable guardrails

- Never invent metrics, dates, quotations or business conclusions.
- Prefer supplied source material over model memory.
- Important claims should carry provenance whenever the source format permits it.
- The final PPTX is a build artifact; the IR and source evidence are authoritative.
- Keep output reproducible where practical: same inputs + version + configuration should produce equivalent structure.
- Avoid repetitive card grids when the content does not justify them; choose layouts from content semantics and template grammar.
- Preserve editability for native PPTX elements whenever the chosen renderer supports it.
- Host agents are adapters. Do not make core presentation logic dependent on a single model or platform.
- A script that exits successfully is **not** sufficient visual validation. A rendered deck must pass the per-page production gate before delivery.
- If visual regression is enabled, **zero failed pages is the release criterion**. Aggregate averages must never hide a bad slide.

## Capability routing

If the host exposes a native PPTX or Office capability, use it where it materially improves fidelity. Otherwise use the portable local renderer. If visual rendering is available, use it for QA before delivery.

## Current V0.1 commands

```bash
ppt-agent markdown-to-ir input.md -o workspace/presentation.json
ppt-agent analyze-pptx reference.pptx -o workspace/template-dna.json
ppt-agent qa-ir workspace/presentation.json
ppt-agent validate-pptx output.pptx -o workspace/page-gate.json
ppt-agent visual-regression reference.pptx output.pptx -o workspace/visual-report.json
```

V0.1 now includes the foundation of the per-page render/validation loop. Later releases will connect the page gate to the Visual Critic and automatic Repair Agent so the final generation loop can repair failed pages autonomously.
