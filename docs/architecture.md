# PPT Agent Architecture

## Objective

PPT Agent is a portable presentation engineering system rather than a prompt-only skill. Host agents
and model providers are adapters around a stable core.

## Layers

1. **Host Adapter** — translates host-agent capabilities and task input into the core contract.
2. **SDK facade** (`ppt_agent.sdk.PptAgent`) — one stable entry point per pipeline stage.
3. **Intelligence Core** — analyzes sources, constructs narrative structure, and plans slides.
4. **Design Intelligence** — extracts Template DNA and chooses layout/style rules.
5. **Universal IR** — canonical presentation representation and source of truth (`ppt_agent.ir`).
6. **Renderer SDK** (`ppt_agent.renderers`) — pluggable IR → artifact engines behind one protocol.
7. **Quality Gates / Critic / Repair** — deterministic checks plus visual review and targeted rebuilds.

## Entry points

Three surfaces, one implementation. Every one of them delegates to `PptAgent`, so the CLI, the MCP
tools and an embedded integration cannot drift apart.

```
ppt-agent CLI ─┐
MCP tools     ─┼─→ ppt_agent.sdk.PptAgent ─→ core modules
Python import ─┘
```

## Module map

| Module | Responsibility |
|---|---|
| `ppt_agent.contracts` | Stable versions, capability model, IR version checks, negotiation |
| `ppt_agent.styling` | Shared style conventions and the single layout algorithm |
| `ppt_agent.ir` | Universal IR dataclasses + `to_dict`/`from_dict` |
| `ppt_agent.markdown` | Markdown → IR (flat mapper) |
| `ppt_agent.story` | Story Architect: Markdown → narrative outline → IR |
| `ppt_agent.template` | PPTX → Template DNA (semantic + OOXML fidelity) |
| `ppt_agent.dna_to_ir` | Template DNA → IR |
| `ppt_agent.renderers.base` | Renderer protocol, `RenderRequest`/`RenderResult` |
| `ppt_agent.renderers.native_pptx` | Native editable PPTX engine (wraps `ppt_agent.renderer`) |
| `ppt_agent.renderers.html` | Visual engine: self-contained printable HTML deck |
| `ppt_agent.renderers.registry` | Registration, preference order, automatic selection, `render_with` |
| `ppt_agent.adapters` | Host protocol, capability detection, declarative host profiles |
| `ppt_agent.mcp` | Dependency-free MCP stdio server and tool surface |
| `ppt_agent.sdk` | High-level facade used by the CLI, MCP and integrations |
| `ppt_agent.page_validation` | Geometry / blank-page gates (rendered and structural) |
| `ppt_agent.visual_critic` | Visual review rules |
| `ppt_agent.visual_regression` | PNG render + SSIM/MAE comparison, rasteriser detection |
| `ppt_agent.fact_registry` | Provenance-backed fact store + claim audit |
| `ppt_agent.delivery` | Delivery policy + bounded repair loop |
| `ppt_agent.manifest` | Per-page delivery manifest |
| `ppt_agent.benchmark` | Reproducible benchmark suite |
| `ppt_agent.release` | Deterministic release manifest and drift verification |

## Import discipline

`import ppt_agent` pulls in nothing beyond the standard library. Heavy engines (`python-pptx`,
Pillow, numpy) are imported by the modules that need them, and the SDK is exposed lazily:

```python
import ppt_agent          # stdlib only
ppt_agent.PptAgent        # resolved on first access, pulls in the pipeline
```

This is enforced in CI by the `dependency-free-core` job, which installs the package with no extras and
still runs `ppt-agent capabilities`.

## Rendering contract

`render_presentation(ir, output)` is the single native code path. `NativePptxRenderer` and
`HtmlRenderer` both consume the **same** layout resolved by `styling.resolve_layout()`, so a
cross-engine comparison compares typography and fidelity, not two divergent layout algorithms.
Rendering is deterministic: the same IR yields the same shape tree.

Components with `x/y/w/h` (inches) are placed absolutely; components without geometry flow top-down
from a purpose-dependent cursor. See `ROADMAP.md` for the v1 scope and known limits.

The repair loop is closed through `Renderer.build_callback(ir, path)`, which returns a `build` callback
accepted by `delivery.run_repair_loop`.

## Capability-driven degradation

The core never assumes it can rasterise a deck. `ppt_agent.contracts.negotiate()` matches what the host
actually grants against what the pipeline would like, and every gap carries a documented fallback:

| Missing | Degradation |
|---|---|
| `render_preview` | Visual critic and regression gates become structural geometry gates |
| `shell` | External rasterisation and Office automation unavailable; pure-Python path only |
| `office_automation` | Portable python-pptx renderer is used instead |
| `browser` | HTML previews are written to disk but not opened |
| `network` | Every input must resolve to a local path |
| `long_running` | Repair loops and benchmarks stay bounded |

Only `filesystem` is fatal. A gate is never silently skipped: the response always names the gates that
ran and the capabilities that were degraded. See `docs/adapters.md`.

## Source-first rule

Never treat the generated PPTX as the canonical source. The presentation IR and its source artifacts
remain authoritative. Repairs should modify the source representation and rebuild the PPTX.

## Portability

The core must not depend on a specific LLM or host. Integrations implement the `HostAdapter` contract.
A host may provide file access, shell execution, browser rendering, PowerPoint automation, or MCP;
capability detection decides which execution route is available. See `docs/mcp.md` and
`docs/adapters.md`.

## Quality gates

A delivery is accepted only when required gates pass:

- schema validity
- content/evidence consistency
- geometry and overflow checks
- render success
- visual review threshold
- final artifact manifest

Failed gates create a repair task. The repair loop is bounded and must preserve provenance.

## Reproducibility

Three levels, all enforced by automation:

1. **IR level** — deterministic rendering, asserted by `tests/test_renderer.py`.
2. **Pipeline level** — same Markdown yields identical IR, PPTX shape tree and HTML, asserted per case
   by `ppt-agent benchmark`.
3. **Release level** — same tree yields the same digest, asserted by `ppt-agent-release verify`.

See `docs/release.md`.
