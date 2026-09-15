# PPT Agent

**PPT Agent** is a universal, agent-native presentation engineering framework.

The goal is not merely to generate a `.pptx`, but to provide a reusable pipeline for:

`source analysis → story architecture → slide planning → visual design → native PPTX rendering → visual QA → automatic repair`

## Design principles

- **Source-first**: the presentation specification is the source of truth; PPTX is a build artifact.
- **Universal IR**: planning and design are independent of any specific LLM, agent host, or renderer.
- **Template DNA**: reference presentations are analyzed into reusable visual/layout rules.
- **Evidence locked**: important claims and numbers can retain provenance back to source material.
- **Visual QA**: rendered slides are inspected for geometry, density, hierarchy, readability and consistency.
- **Repair loop**: failed checks feed targeted repairs and rebuilds instead of manual patching.
- **Portable**: adapters allow the same core to be used by Codex, WorkBuddy, 豆包工作 and other agent hosts.

## Architecture

```text
Host Agent
   │
   ▼
Adapter Layer
   │
   ▼
PPT Agent Core
 ├─ Document Analyzer
 ├─ Story Architect
 ├─ Slide Planner
 ├─ Visual Designer
 └─ Orchestrator
   │
   ▼
Universal Presentation IR
   │
   ├───────────────┬────────────────┐
   ▼               ▼                ▼
Native PPTX     Visual Preview   Office Adapter
Engine          HTML/SVG          PowerPoint
   │               │                │
   └───────────────┴────────────────┘
                   ▼
              Render / QA
                   │
              ┌────┴────┐
              ▼         ▼
             PASS      FAIL
              │         │
              │      Repair
              │         │
              └────┬────┘
                   ▼
              Final PPTX
```

## Repository status

This repository is the initial V0.1 foundation. The architecture is intentionally modular so later releases can add Template DNA, renderers, MCP, host adapters, visual critics and benchmark suites without replacing the core IR.

## Roadmap

- V0.1 — core architecture, Universal IR, CLI skeleton, portable Skill contract
- V0.2 — PPTX inspection and Template DNA extraction
- V0.3 — native PPTX renderer + render/QA loop
- V0.4 — Fact Registry, provenance and Fact Lock
- V0.5 — Visual Critic and Repair Agent
- V0.6 — MCP server and generic agent adapter
- V0.7 — Codex / WorkBuddy / 豆包 adapters
- V1.0 — stable Universal Presentation Intelligence Engine

## License

The core license is intentionally not finalized in this first foundation commit. We will select and add the final open-source license after reviewing implementation dependencies and the intended product/commercial model.
