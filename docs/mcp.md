# MCP Server

PPT Agent ships a dependency-free [Model Context Protocol](https://modelcontextprotocol.io) server so any
MCP-capable host can drive the pipeline without bespoke glue code.

```bash
ppt-agent-mcp --workspace /path/to/sandbox          # stdio transport
ppt-agent mcp --workspace /path/to/sandbox          # same server via the CLI
```

Add it to a host's MCP configuration:

```json
{
  "mcpServers": {
    "ppt-agent": {
      "command": "ppt-agent-mcp",
      "args": ["--workspace", "${workspaceFolder}"]
    }
  }
}
```

## Why it has no dependencies

The transport is plain newline-delimited JSON-RPC 2.0 over stdin/stdout, implemented on the standard
library alone. Installing the official MCP SDK would add a runtime dependency to a project whose whole
premise is that the core stays portable. The protocol surface actually needed by a tool host is small
and stable, so it is implemented directly in `ppt_agent/mcp/`.

## Protocol surface

| Method | Behaviour |
|---|---|
| `initialize` | Agrees on the newest protocol version in `MCP_PROTOCOL_VERSIONS`, returns server info and instructions |
| `notifications/initialized`, `notifications/cancelled` | Accepted and never answered |
| `ping` | Returns `{}` |
| `tools/list` | Returns all 13 tools with JSON Schema input definitions |
| `tools/call` | Executes a tool; failures come back as `isError: true` content, not JSON-RPC errors |
| `resources/list`, `resources/templates/list`, `prompts/list` | Empty listings (reserved for later use) |

Unknown methods return `-32601`, unknown tool names `-32602`, malformed JSON `-32700`.
stdout carries protocol traffic only; diagnostics go to stderr.

## Tools

All ten of the IR-route tools are thin wrappers over `ppt_agent.sdk.PptAgent`, so the tool surface
cannot drift from the SDK or the CLI; the clone trio wraps `PptAgent.clone_*` the same way.

| Tool | Purpose |
|---|---|
| `ppt_agent_capabilities` | Contract versions, host capabilities, negotiation outcome, renderer inventory. **Call this first.** |
| `ppt_agent_analyze_pptx` | Reference PPTX → Template DNA (structure, typography, colour, OOXML fidelity) |
| `ppt_agent_markdown_to_ir` | Markdown → IR, via the Story Architect (`mode: story`) or the flat mapper (`mode: flat`) |
| `ppt_agent_ir_to_pptx` | IR → editable native PPTX |
| `ppt_agent_render_html` | IR → self-contained printable HTML deck |
| `ppt_agent_validate_ir` | Schema, identity and geometry gates on the IR |
| `ppt_agent_validate_pptx` | Per-page delivery gate; always states which gates actually ran |
| `ppt_agent_audit_facts` | Check every textual claim against a fact registry |
| `ppt_agent_build` | End to end: plan → build → gate, returning the delivery manifest |
| `ppt_agent_host_profile` | Inspect capability negotiation for a named host platform |
| `ppt_agent_clone_plan` | Clone route step 1: shells by role + per-page-kind DNA summaries + valid roles/kits |
| `ppt_agent_clone_build` | Clone route step 2: render a JSON page plan through the template's own shells, then audit |
| `ppt_agent_clone_audit` | Clone route step 3: run the six-kind page audit over any deck |

### Typical call sequence

```text
ppt_agent_capabilities         # what can this host actually do?
      ↓
ppt_agent_markdown_to_ir       # or ppt_agent_analyze_pptx first, for a reference deck
      ↓
ppt_agent_build                # IR + PPTX + HTML + gate + manifest
      ↓
ppt_agent_audit_facts          # only when the deck carries metrics or conclusions
```

## The clone route on the MCP surface

The IR/design route above re-draws every page from theme tokens. When the deliverable is
"looks like THIS template", three more tools drive the clone-shell route — the one where
untouched photos / logos / freeforms stay byte-identical — without writing any Python:

```text
ppt_agent_clone_plan(template)
        # shells by role, per-page-kind DNA, the ornaments to inherit, valid kits
        ↓
ppt_agent_clone_build(template, pages=[...], output)
        # one shell per spec: cover/closing rebuild their chrome, section/toc inherit
        # the layout band, content pages dispatch to the named page kit; then audit
        ↓
ppt_agent_clone_audit(pptx)    # zero issues is the delivery bar
```

A `pages` entry is plain data: `{"role": "content", "title": "...", "lead": "...",
"kit": "four_role_cards", "cards": [...], "note": "..."}`. Kit kwargs are the `page_kits`
signatures verbatim, so kits can grow without the tool surface changing. Bad plans fail
with named errors (unknown role/kit, missing kit data, insufficient shells) before any
file is written; the built deck comes back with its `audit` report attached.

## Workspace containment

`--workspace` is a hard boundary. Every output path is resolved against it and a path that escapes the
root is rejected:

```json
{"error": "output path escapes the workspace root /srv/sandbox: /srv/escape"}
```

Input paths may be absolute — the host is explicitly asking to read a file it can see — but nothing is
ever written outside the workspace. This keeps a runaway tool call from scattering build artifacts
across a user's machine.

## Degradation, not silence

When the host has no rasteriser, `ppt_agent_validate_pptx` does not disappear and does not pretend to
have run image checks. It runs the structural geometry gate and says so:

```json
{
  "mode": "structural",
  "degraded": ["render_preview"],
  "page_gate": {"mode": "structural", "passed": true}
}
```

`"mode": "rendered"` with an empty `degraded` list means the full page, critic and visual-regression
gates ran.

## Testing the server by hand

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | ppt-agent-mcp --workspace ./sandbox
```

`tests/test_mcp_server.py` runs the same loop against in-memory streams, covering protocol negotiation,
notification silence, error codes, workspace containment and the build/audit tools end to end.
