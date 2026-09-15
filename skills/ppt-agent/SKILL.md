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
7. **Render and inspect** geometry, content density, readability and visual consistency.
8. **Run quality gates**. Failed gates block delivery.
9. **Repair the source/IR/rules**, rebuild, rerender and recheck. Do not hide defects with untracked final-file patches.
10. **Deliver** only the validated presentation and its manifest/evidence artifacts when requested.

## Non-negotiable guardrails

- Never invent metrics, dates, quotations or business conclusions.
- Prefer supplied source material over model memory.
- Important claims should carry provenance whenever the source format permits it.
- The final PPTX is a build artifact; the IR and source evidence are authoritative.
- Keep output reproducible where practical: same inputs + version + configuration should produce equivalent structure.
- Avoid repetitive card grids when the content does not justify them; choose layouts from content semantics and template grammar.
- Preserve editability for native PPTX elements whenever the chosen renderer supports it.
- Host agents are adapters. Do not make core presentation logic dependent on a single model or platform.

## Capability routing

If the host exposes a native PPTX or Office capability, use it where it materially improves fidelity. Otherwise use the portable local renderer. If visual rendering is available, use it for QA before delivery.

## Current V0.1 commands

```bash
ppt-agent markdown-to-ir input.md -o workspace/presentation.json
ppt-agent analyze-pptx reference.pptx -o workspace/template-dna.json
ppt-agent qa-ir workspace/presentation.json
```

V0.1 does not claim to be a full PPTX generator yet; later releases add native rendering, visual critique and automatic repair.
