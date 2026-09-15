# PPT Agent Skill

## Purpose

Use PPT Agent to create or revise professional presentation decks from source documents and, when provided, reference PPTX templates.

## Operating contract

1. Inspect all provided source materials before designing slides.
2. Extract facts, claims, constraints and source provenance.
3. Analyze reference presentation structure and visual language when a template is provided.
4. Build a narrative spine and slide plan before rendering.
5. Produce a Universal Presentation IR as the canonical source.
6. Render an editable PPTX using an available renderer.
7. Render previews and run geometry/content/evidence/visual QA.
8. If a gate fails, create a targeted repair, modify the source representation, rebuild, and rerun QA.
9. Deliver only after required gates pass and the final artifact is recorded in a delivery manifest.

## Non-negotiable quality rules

- Do not invent metrics, dates, names or claims.
- Preserve source terminology unless the user explicitly requests rewriting.
- Do not silently replace user-provided template structure with generic AI card grids.
- Prefer content-driven layouts over repetitive decorative components.
- Keep important numbers traceable to source evidence when provenance is available.
- Never patch only the final PPTX when the underlying source representation can be corrected and rebuilt.

## Host portability

This skill is host-neutral. A host adapter may expose local files, shell tools, browser rendering, PowerPoint automation, or MCP. The core should select capabilities rather than assume a particular host or model.

## Default workflow

`Analyze → Evidence → Story → Plan → Design → IR → Build → Render → Critic → Repair → Validate → Deliver`

## Failure handling

Repairs must be bounded. Preserve the failing artifact and QA report for diagnosis. Prefer fixing the smallest source-level cause rather than globally changing a style that may affect unrelated slides.
