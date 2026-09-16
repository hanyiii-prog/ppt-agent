# Adapters

An adapter is the **only** place that knows how to reach a specific agent host. The core never imports
a host SDK, which is what keeps PPT Agent agent-agnostic in practice rather than only in the README.

```python
from ppt_agent import PptAgent
from ppt_agent.adapters import create_adapter, default_adapter, GenericAdapter

PptAgent(create_adapter("workbuddy"))   # declarative host profile
PptAgent(default_adapter())             # the local machine
PptAgent(GenericAdapter())              # filesystem only, for hostile sandboxes
```

## Capabilities

Seven capabilities are modelled (`ppt_agent.contracts.CAPABILITY_SPECS`):

| Capability | Meaning |
|---|---|
| `filesystem` | read and write local files — **the only fatal one** |
| `shell` | execute local processes |
| `render_preview` | rasterise slides to images for visual QA |
| `office_automation` | drive PowerPoint/Office natively |
| `browser` | open or inspect rendered previews |
| `network` | reach external services |
| `long_running` | run multi-minute jobs without a host timeout |

## Declared vs effective

A host profile states what a platform *typically* offers. `effective()` re-checks the runtime, because a
claim is not a fact:

```python
adapter = create_adapter("codex")
adapter.describe().to_dict()
# {'declared': ['filesystem', 'long_running', 'render_preview', 'shell'],
#  'effective': ['filesystem', 'long_running', 'shell'],   # no LibreOffice on this box
#  ...}
```

`render_preview` is marked *runtime gated*: asking for it when no rasteriser exists raises a typed
`CapabilityError` with the documented fallback, rather than failing later inside a tool call.

```python
from ppt_agent.adapters import CapabilityError

try:
    adapter.render_preview("deck.pptx", "pages/")
except CapabilityError as exc:
    print(exc.capability, exc)   # render_preview ... no rasteriser: gates degrade to structural checks
```

## Negotiation

`negotiate()` matches requirements against effective capabilities and reports a **documented fallback**
for each gap instead of silently dropping it.

```python
adapter.negotiate(("filesystem", "render_preview")).to_dict()
# {'ok': True,
#  'granted': ['filesystem', 'long_running', 'shell'],
#  'missing': ['render_preview'],
#  'fallbacks': ['structural_gate_only'],
#  'notes': ['render_preview: no rasteriser: visual review and regression gates degrade to '
#            'structural geometry checks']}
```

`ok` is `False` only when a **fatal** capability (`filesystem`) is missing. Everything else degrades.
`allow_fallback=False` turns any gap into a hard failure, for hosts that would rather stop than
silently deliver fewer checks.

## Host profiles

`HOST_PROFILES` ships declarative defaults for `codex`, `workbuddy`, `doubao`, `claude` and `chatgpt`.
They are starting points, not assertions about the world — override them per deployment:

```python
create_adapter("chatgpt", add=("render_preview",), remove=("network",))
```

Or subclass for full control:

```python
from ppt_agent.adapters import HostAdapter
from ppt_agent.contracts import CapabilitySet

class MyPlatform(HostAdapter):
    name = "my-platform"
    capabilities = CapabilitySet.of("filesystem", "shell", "render_preview", "long_running")
    notes = ("renders through the platform's own PPTX service",)
```

## Adapter API

| Method | Requires | Notes |
|---|---|---|
| `describe()` | — | Declared and effective capabilities plus protocol version |
| `effective()` / `provides()` / `require()` / `check()` | — | Capability queries and typed failures |
| `resolve_path`, `ensure_dir`, `read_text`, `read_json`, `write_text`, `write_json` | `filesystem` | Create parent directories on write |
| `run(argv)` | `shell` | **Never** uses a shell; a bare string argument raises `TypeError` |
| `which(executable)` | `shell` | Path lookup |
| `render_preview(pptx, out)` | `render_preview` | LibreOffice + pdftoppm |
| `open_preview(path)` | `browser` | Returns `False` by default; hosts override |
| `convert_with_office(pptx, out, target)` | `office_automation` | Unimplemented in the built-ins by design |

`run()` only accepts a sequence, so arguments can never be re-parsed by a shell — command injection is
structurally impossible rather than filtered against.

## Capability report

```bash
ppt-agent capabilities                 # human readable summary
ppt-agent capabilities --json          # the full descriptor
ppt-agent capabilities --host workbuddy
```

The same payload is served by the `ppt_agent_capabilities` MCP tool and validated by
`schemas/capability-descriptor.schema.json`.
