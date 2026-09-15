# PPT Agent Architecture

## Objective

PPT Agent is designed as a portable presentation engineering system rather than a prompt-only skill. Host agents and model providers are adapters around a stable core.

## Layers

1. **Host Adapter** — translates host-agent capabilities and task input into the core contract.
2. **Intelligence Core** — analyzes sources, constructs narrative structure, and plans slides.
3. **Design Intelligence** — extracts Template DNA and chooses layout/style rules.
4. **Universal IR** — canonical presentation representation and source of truth.
5. **Rendering** — native PPTX and future visual/Office engines.
6. **QA / Critic / Repair** — deterministic checks plus visual review and targeted rebuilds.

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
