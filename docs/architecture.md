# PPT Agent Architecture

## Objective

PPT Agent is designed as a portable presentation engineering system rather than a prompt-only skill. Host agents and model providers are adapters around a stable core.

## Layers

1. **Host Adapter** — translates host-agent capabilities and task input into the core contract.
2. **Intelligence Core** — analyzes sources, constructs narrative structure, and plans slides.
3. **Design Intelligence** — extracts Template DNA and chooses layout/style rules.
4. **Universal IR** — canonical presentation representation and source of truth (`ppt_agent.ir`).
5. **Rendering** — native PPTX engine (`ppt_agent.renderer`), plus future visual/Office engines.
6. **QA / Critic / Repair** — deterministic checks plus visual review and targeted rebuilds.

## Module map

| Module | Responsibility |
|---|---|
| `ppt_agent.ir` | Universal IR dataclasses + `to_dict`/`from_dict` |
| `ppt_agent.markdown` | Markdown → IR |
| `ppt_agent.story` | Story Architect: Markdown → narrative outline → IR |
| `ppt_agent.template` | PPTX → Template DNA (semantic + OOXML fidelity) |
| `ppt_agent.dna_to_ir` | Template DNA → IR |
| `ppt_agent.renderer` | IR → editable native PPTX |
| `ppt_agent.page_validation` | Geometry / blank-page gate |
| `ppt_agent.visual_critic` | Visual review rules |
| `ppt_agent.visual_regression` | PNG render + SSIM/MAE comparison |
| `ppt_agent.fact_registry` | Provenance-backed fact store + claim audit |
| `ppt_agent.delivery` | Delivery policy + bounded repair loop |

## Rendering contract

`render_presentation(ir, output)` is the single entry point for producing a PPTX. It is deterministic: the same IR yields the same shape tree. Components with `x/y/w/h` (inches) are placed absolutely; components without geometry flow top-down. See `ROADMAP.md` for the v1 scope and known limits.

The repair loop is closed through `renderer.make_ir_build(ir, path)`, which returns a `build` callback accepted by `delivery.run_repair_loop`.

## Source-first rule

Never treat the generated PPTX as the canonical source. The presentation IR and its source artifacts remain authoritative. Repairs should modify the source representation and rebuild the PPTX.

## Portability

The core must not depend on a specific LLM or host. Integrations should implement explicit adapter contracts. A host may provide file access, shell execution, browser rendering, PowerPoint automation, or MCP; capability detection decides which execution route is available.

## Quality gates

A delivery is accepted only when required gates pass:

- schema validity
- content/evidence consistency
- geometry and overflow checks
- render success
- visual review threshold
- final artifact manifest

Failed gates create a repair task. The repair loop is bounded and must preserve provenance.
