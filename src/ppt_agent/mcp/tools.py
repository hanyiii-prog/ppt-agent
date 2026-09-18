"""MCP tool surface.

Every tool is a thin wrapper over `ppt_agent.sdk.PptAgent`, so the tool surface
can never drift from the CLI or the SDK.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..adapters import create_adapter
from ..contracts import contract_descriptor
from ..ir import Presentation
from ..sdk import PptAgent
from .protocol import INVALID_PARAMS, JsonRpcError


class ToolError(RuntimeError):
    """A tool level failure, returned inside the result rather than as JSON-RPC error."""


@dataclass
class ToolContext:
    """Execution context: one SDK instance, the sandbox, and the sampling session."""

    agent: PptAgent
    workspace: Path
    # ppt_agent.mcp.sampling.SamplingSession | None -- typed loosely so the
    # tools module stays importable without the sampling transport. Tools that
    # want the host model go through llm.select_provider(self.session).
    session: Any = None

    def output_path(self, value: str) -> Path:
        """Resolve an output path, refusing to escape the workspace root."""
        candidate = Path(value)
        target = candidate.resolve() if candidate.is_absolute() else (self.workspace / candidate).resolve()
        root = self.workspace.resolve()
        if target != root and root not in target.parents:
            raise ToolError(f"output path escapes the workspace root {root}: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def input_path(self, value: str) -> Path:
        candidate = Path(value)
        target = candidate.resolve() if candidate.is_absolute() else (self.workspace / candidate).resolve()
        if not target.exists():
            raise ToolError(f"input path does not exist: {target}")
        return target


# --- argument helpers ------------------------------------------------------
def _require(arguments: dict[str, Any], key: str) -> Any:
    if key not in arguments or arguments[key] in (None, ""):
        raise ToolError(f"missing required argument: {key}")
    return arguments[key]


def _string(arguments: dict[str, Any], key: str) -> str:
    value = _require(arguments, key)
    if not isinstance(value, str):
        raise ToolError(f"argument {key} must be a string")
    return value


def _optional_string(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ToolError(f"argument {key} must be a string")
    return value


def _read_text(arguments: dict[str, Any], context: ToolContext, *, source_key: str, inline_key: str) -> str:
    source = _optional_string(arguments, source_key)
    if source:
        return context.input_path(source).read_text(encoding="utf-8")
    inline = _optional_string(arguments, inline_key)
    if inline is None:
        raise ToolError(f"provide either {inline_key!r} (inline text) or {source_key!r} (a path)")
    return inline


def _load_ir(arguments: dict[str, Any], context: ToolContext) -> Presentation:
    payload = arguments.get("ir")
    if isinstance(payload, dict):
        return Presentation.from_dict(payload)
    ir_path = _optional_string(arguments, "ir_path")
    if ir_path:
        return context.agent.load_ir(context.input_path(ir_path))
    raise ToolError("provide either 'ir' (an IR object) or 'ir_path' (a path to IR JSON)")


def _facts_of(arguments: dict[str, Any]) -> list[dict[str, Any]] | None:
    facts = arguments.get("facts")
    if facts is None:
        return None
    if not isinstance(facts, list) or not all(isinstance(item, dict) for item in facts):
        raise ToolError("'facts' must be an array of objects")
    return facts


# --- tools ----------------------------------------------------------------
def tool_capabilities(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    return context.agent.capabilities()


def tool_analyze_pptx(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    source = context.input_path(_string(arguments, "source"))
    dna = context.agent.analyze_template(source)
    presentation = dna.get("presentation") or {}
    result: dict[str, Any] = {
        "source": str(source),
        "slide_count": presentation.get("slide_count"),
        "slide_size_inches": presentation.get("slide_size_inches"),
        "tokens": sorted(dna.keys()),
    }
    output = _optional_string(arguments, "output")
    if output:
        target = context.output_path(output)
        target.write_text(json.dumps(dna, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["dna_path"] = str(target)
    return result


def tool_markdown_to_ir(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    markdown = _read_text(arguments, context, source_key="source", inline_key="markdown")
    mode = (_optional_string(arguments, "mode") or "story").lower()
    if mode not in {"story", "flat"}:
        raise ToolError("'mode' must be 'story' or 'flat'")

    if mode == "story":
        presentation = context.agent.plan(
            markdown,
            title=_optional_string(arguments, "title"),
            audience=_optional_string(arguments, "audience"),
            objective=_optional_string(arguments, "objective"),
        )
    else:
        presentation = context.agent.parse(markdown, source_id="markdown")

    result: dict[str, Any] = {
        "mode": mode,
        "title": presentation.title,
        "slide_count": len(presentation.slides),
        "ir": presentation.to_dict(),
        "qa": context.agent.validate_ir(presentation),
    }
    output = _optional_string(arguments, "output")
    if output:
        result["ir_path"] = str(context.agent.save_ir(presentation, context.output_path(output)))
    return result


def tool_ir_to_pptx(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    presentation = _load_ir(arguments, context)
    output = context.output_path(_string(arguments, "output"))
    result = context.agent.render(
        presentation, output, renderer=_optional_string(arguments, "renderer")
    )
    return result.to_dict()


def tool_render_html(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    presentation = _load_ir(arguments, context)
    output = context.output_path(_string(arguments, "output"))
    from ..renderers import render_with

    return render_with(presentation, output, renderer="html").to_dict()


def tool_validate_ir(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    if isinstance(arguments.get("ir"), dict) or _optional_string(arguments, "ir_path"):
        presentation = _load_ir(arguments, context)
        return context.agent.validate_ir(presentation)
    ir_path = _optional_string(arguments, "path")
    if ir_path:
        return context.agent.validate_ir(context.agent.load_ir(context.input_path(ir_path)))
    raise ToolError("provide 'ir', 'ir_path' or 'path'")


def tool_validate_pptx(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    deck = context.input_path(_string(arguments, "pptx"))
    reference = _optional_string(arguments, "reference")
    workspace = _optional_string(arguments, "workspace") or "qa"
    report = context.agent.gate(
        deck,
        workspace=context.output_path(workspace),
        reference=context.input_path(reference) if reference else None,
    )
    output = _optional_string(arguments, "output")
    if output:
        target = context.output_path(output)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["report_path"] = str(target)
    return report


def tool_audit_facts(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    presentation = _load_ir(arguments, context)
    return context.agent.audit_facts(presentation, _facts_of(arguments))


def tool_build(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    out_dir = context.output_path(_string(arguments, "out_dir"))
    has_ir = isinstance(arguments.get("ir"), dict) or bool(_optional_string(arguments, "ir_path"))
    markdown: str | None = None
    if not has_ir:
        markdown = _read_text(arguments, context, source_key="source", inline_key="markdown")

    outcome = context.agent.build(
        out_dir=out_dir,
        markdown=markdown,
        presentation=_load_ir(arguments, context) if has_ir else None,
        title=_optional_string(arguments, "title"),
        audience=_optional_string(arguments, "audience"),
        objective=_optional_string(arguments, "objective"),
        renderer=_optional_string(arguments, "renderer"),
        template=context.input_path(_string(arguments, "template")) if _optional_string(arguments, "template") else None,
        reference=context.input_path(_string(arguments, "reference")) if _optional_string(arguments, "reference") else None,
        gate=bool(arguments.get("gate", True)),
        emit_html=bool(arguments.get("emit_html", True)),
        facts=_facts_of(arguments),
        stem=_optional_string(arguments, "stem") or "presentation",
    )
    return outcome.to_dict()


def tool_host_profile(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    host = _string(arguments, "host")
    try:
        adapter = create_adapter(
            host,
            add=arguments.get("add") or (),
            remove=arguments.get("remove") or (),
        )
    except KeyError as exc:
        raise ToolError(str(exc)) from None
    required = arguments.get("required") or ()
    if not isinstance(required, (list, tuple)):
        raise ToolError("'required' must be an array of capability names")
    return {
        "adapter": adapter.describe().to_dict(),
        "negotiation": adapter.negotiate(required).to_dict(),
    }


def _page_specs(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    pages = arguments.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ToolError("'pages' must be a non-empty array of page-spec objects")
    if not all(isinstance(page, dict) for page in pages):
        raise ToolError("every entry in 'pages' must be an object")
    return pages


def tool_clone_plan(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    template = context.input_path(_string(arguments, "template"))
    return context.agent.clone_plan(template)


def tool_clone_build(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    template = context.input_path(_string(arguments, "template"))
    pages = _page_specs(arguments)
    output = context.output_path(_string(arguments, "output"))
    return context.agent.clone_build(
        template, pages, output, audit=bool(arguments.get("audit", True))
    )


def tool_clone_audit(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    deck = context.input_path(_string(arguments, "pptx"))
    return context.agent.clone_audit(deck)


# --- fidelity engine (V1.11) ----------------------------------------------
def tool_fidelity_extract(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    from ..fidelity import extract_fidelity_dna

    source = context.input_path(_string(arguments, "source"))
    slide_index = int(arguments.get("slide", 1))
    dna = extract_fidelity_dna(source, slide_index=slide_index)
    summary = {
        "source": str(source),
        "slide_index": slide_index,
        "schema": dna.get("schema"),
        "page_kind": dna.get("page_kind"),
        "surface_role": dna.get("surface_role"),
        "presentation": dna.get("presentation"),
        "layer_count": len((dna.get("slide") or {}).get("shapes", [])),
        "layout_layer_count": len((dna.get("layout") or {}).get("shapes", [])),
        "master_layer_count": len((dna.get("master") or {}).get("shapes", [])),
        "asset_count": len(dna.get("assets", {})),
        "placeholder_resolutions": len(dna.get("placeholder_resolutions", [])),
        "toc": dna.get("toc"),
    }
    output = _optional_string(arguments, "output")
    if output:
        target = context.output_path(output)
        target.write_text(json.dumps(dna, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary["dna_path"] = str(target)
    return summary


def tool_fidelity_diff(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    from ..fidelity import extract_fidelity_dna
    from ..fidelity_diff import compare_dna

    reference = context.input_path(_string(arguments, "reference"))
    candidate = context.input_path(_string(arguments, "candidate"))
    slide_index = int(arguments.get("slide", 1))
    report = compare_dna(
        extract_fidelity_dna(reference, slide_index=slide_index),
        extract_fidelity_dna(candidate, slide_index=slide_index),
        tolerance=float(arguments.get("tolerance", 0.0005)),
    )
    payload = report.to_dict()
    payload.update({
        "reference": str(reference),
        "candidate": str(candidate),
        "slide_index": slide_index,
    })
    output = _optional_string(arguments, "output")
    if output:
        target = context.output_path(output)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload["report_path"] = str(target)
    return payload


def tool_fidelity_repair(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    from ..fidelity_pipeline import FidelityRepairExhausted, repair_deck

    reference = context.input_path(_string(arguments, "reference"))
    candidate = context.input_path(_string(arguments, "candidate"))
    output = context.output_path(_string(arguments, "output"))
    workspace = context.output_path(_optional_string(arguments, "workspace") or "fidelity-repair")
    try:
        result = repair_deck(
            reference, candidate, workspace,
            max_iterations=int(arguments.get("max_iterations", 3)),
            render=bool(arguments.get("render", False)),
        )
    except FidelityRepairExhausted as exc:
        result = exc.payload
    result["repaired_output"] = str(output)
    import shutil

    if result.get("candidate_final") and Path(result["candidate_final"]) != output:
        shutil.copy(result["candidate_final"], output)
    return result


def tool_fidelity_validate(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    from ..fidelity_pipeline import validate_deck_fidelity

    reference = context.input_path(_string(arguments, "reference"))
    candidate = context.input_path(_string(arguments, "candidate"))
    workspace = context.output_path(_optional_string(arguments, "workspace") or "fidelity-validate")
    result = validate_deck_fidelity(
        reference, candidate, workspace,
        render=bool(arguments.get("render", True)),
        threshold_ssim=float(arguments.get("ssim", 0.995)),
        threshold_mae=float(arguments.get("mae", 0.005)),
        threshold_mismatch=float(arguments.get("mismatch", 0.01)),
    )
    output = _optional_string(arguments, "output")
    if output:
        target = context.output_path(output)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report_path"] = str(target)
    return result


def tool_narrative_plan(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    from ..llm.provider import llm_fn_from_provider, select_provider
    from ..narrative_engine import build_narrative
    from ..parsers import parse_markdown

    text = _read_text(arguments, context, source_key="source", inline_key="markdown")
    document = parse_markdown(text)
    provider = select_provider(context.session)
    if provider is None:
        # red line 6: no sampling capability -> the LLM was never attempted
        narrative = build_narrative(document)
    else:
        narrative = build_narrative(document, llm_fn=llm_fn_from_provider(provider))
    narrative["source"] = "mcp"
    return narrative


TOOL_IMPLEMENTATIONS: dict[str, Callable[[dict[str, Any], ToolContext], dict[str, Any]]] = {
    "ppt_agent_capabilities": tool_capabilities,
    "ppt_agent_analyze_pptx": tool_analyze_pptx,
    "ppt_agent_markdown_to_ir": tool_markdown_to_ir,
    "ppt_agent_ir_to_pptx": tool_ir_to_pptx,
    "ppt_agent_render_html": tool_render_html,
    "ppt_agent_validate_ir": tool_validate_ir,
    "ppt_agent_validate_pptx": tool_validate_pptx,
    "ppt_agent_audit_facts": tool_audit_facts,
    "ppt_agent_build": tool_build,
    "ppt_agent_host_profile": tool_host_profile,
    "ppt_agent_clone_plan": tool_clone_plan,
    "ppt_agent_clone_build": tool_clone_build,
    "ppt_agent_clone_audit": tool_clone_audit,
    "ppt_agent_fidelity_extract": tool_fidelity_extract,
    "ppt_agent_fidelity_diff": tool_fidelity_diff,
    "ppt_agent_fidelity_repair": tool_fidelity_repair,
    "ppt_agent_fidelity_validate": tool_fidelity_validate,
    "ppt_agent_narrative_plan": tool_narrative_plan,
}


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


_PROP_IR = {"type": "object", "description": "A Universal Presentation IR object"}
_PROP_IR_PATH = {"type": "string", "description": "Path to an IR JSON file"}
_PROP_FACTS = {
    "type": "array",
    "description": "Registered facts used to audit every textual claim in the deck",
    "items": {
        "type": "object",
        "properties": {
            "claim": {"type": "string"},
            "source_id": {"type": "string"},
            "locator": {"type": "string"},
            "quote": {"type": "string"},
        },
        "required": ["claim", "source_id"],
    },
}
_PROP_STORY_META = {
    "title": {"type": "string", "description": "Deck title override"},
    "audience": {"type": "string", "description": "Who will read the deck"},
    "objective": {"type": "string", "description": "What the deck must achieve"},
}

_PROP_CLONE_PAGES = {
    "type": "array",
    "description": (
        "Page plan, in final order. Each spec: role (cover/toc/section/content/"
        "closing) plus its data -- cover: pill/title/meta; closing: title/sub/meta; "
        "section: title/lines; toc: title/items/note; content: title/lead/kit + the "
        "kit's data (four_role_cards, org_chart, two_panel_list, quad_cards, "
        "column_cards, stage_cards, progress_timeline, stage_timeline). Unknown "
        "keys are forwarded to the kit as keyword arguments."
    ),
    "items": {
        "type": "object",
        "properties": {
            "role": {"type": "string", "enum": ["cover", "toc", "section", "content", "closing"]},
            "kit": {"type": "string", "enum": ["four_role_cards", "org_chart", "two_panel_list",
                                               "quad_cards", "column_cards", "stage_cards",
                                               "progress_timeline", "stage_timeline"]},
            "title": {"type": "string"},
            "lead": {"type": "string"},
        },
        "required": ["role"],
        "additionalProperties": True,
    },
}

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "ppt_agent_capabilities",
        "description": (
            "Report the stable contract versions, host capabilities, capability negotiation "
            "outcome and available renderers. Call this first to learn what the host can do."
        ),
        "inputSchema": _schema({}),
    },
    {
        "name": "ppt_agent_analyze_pptx",
        "description": "Extract Template DNA (structure, typography, colour, OOXML fidelity) from a reference PPTX.",
        "inputSchema": _schema(
            {
                "source": {"type": "string", "description": "Path to the reference PPTX"},
                "output": {"type": "string", "description": "Optional path to write the full Template DNA JSON"},
            },
            ["source"],
        ),
    },
    {
        "name": "ppt_agent_markdown_to_ir",
        "description": (
            "Turn Markdown into Universal Presentation IR. mode='story' (default) runs the "
            "Story Architect first; mode='flat' maps headings straight to slides."
        ),
        "inputSchema": _schema(
            {
                "markdown": {"type": "string", "description": "Markdown content inline"},
                "source": {"type": "string", "description": "Path to a Markdown file (alternative to markdown)"},
                "mode": {"type": "string", "enum": ["story", "flat"]},
                "output": {"type": "string", "description": "Optional path to write the IR JSON"},
                **_PROP_STORY_META,
            }
        ),
    },
    {
        "name": "ppt_agent_ir_to_pptx",
        "description": "Render Universal IR into an editable native PPTX.",
        "inputSchema": _schema(
            {
                "ir": _PROP_IR,
                "ir_path": _PROP_IR_PATH,
                "output": {"type": "string", "description": "Destination .pptx path"},
                "renderer": {"type": "string", "description": "Renderer name; defaults to the highest fidelity engine"},
            },
            ["output"],
        ),
    },
    {
        "name": "ppt_agent_render_html",
        "description": "Render Universal IR into one self-contained, printable HTML deck for fast visual review.",
        "inputSchema": _schema(
            {"ir": _PROP_IR, "ir_path": _PROP_IR_PATH, "output": {"type": "string"}},
            ["output"],
        ),
    },
    {
        "name": "ppt_agent_validate_ir",
        "description": "Run the IR quality gates: schema, identity and geometry checks.",
        "inputSchema": _schema({"ir": _PROP_IR, "ir_path": _PROP_IR_PATH, "path": {"type": "string"}}),
    },
    {
        "name": "ppt_agent_validate_pptx",
        "description": (
            "Run the delivery gate over every slide. Degrades to structural geometry checks when the "
            "host has no rasteriser; the response always states which gates ran."
        ),
        "inputSchema": _schema(
            {
                "pptx": {"type": "string", "description": "Path to the candidate deck"},
                "reference": {"type": "string", "description": "Optional reference deck for visual regression"},
                "workspace": {"type": "string", "description": "Working directory for renders, relative to the workspace"},
                "output": {"type": "string", "description": "Optional path to write the gate report JSON"},
            },
            ["pptx"],
        ),
    },
    {
        "name": "ppt_agent_audit_facts",
        "description": "Check every textual claim in the IR against a fact registry and list unsupported claims.",
        "inputSchema": _schema({"ir": _PROP_IR, "ir_path": _PROP_IR_PATH, "facts": _PROP_FACTS}),
    },
    {
        "name": "ppt_agent_build",
        "description": (
            "End to end: plan, build, gate. Writes IR, PPTX and HTML artifacts and returns the "
            "delivery manifest."
        ),
        "inputSchema": _schema(
            {
                "markdown": {"type": "string"},
                "source": {"type": "string"},
                "ir": _PROP_IR,
                "ir_path": _PROP_IR_PATH,
                "out_dir": {"type": "string", "description": "Output directory inside the workspace"},
                "stem": {"type": "string", "description": "Base filename for the artifacts"},
                "renderer": {"type": "string"},
                "template": {
                    "type": "string",
                    "description": "Reference PPTX whose colours, fonts and type scale seed the design theme",
                },
                "reference": {"type": "string"},
                "gate": {"type": "boolean", "description": "Run the delivery gate (default true)"},
                "emit_html": {"type": "boolean", "description": "Also emit the HTML preview (default true)"},
                "facts": _PROP_FACTS,
                **_PROP_STORY_META,
            },
            ["out_dir"],
        ),
    },
    {
        "name": "ppt_agent_host_profile",
        "description": "Inspect how a named host platform (codex, workbuddy, doubao, claude, chatgpt) negotiates capabilities.",
        "inputSchema": _schema(
            {
                "host": {"type": "string"},
                "add": {"type": "array", "items": {"type": "string"}},
                "remove": {"type": "array", "items": {"type": "string"}},
                "required": {"type": "array", "items": {"type": "string"}},
            },
            ["host"],
        ),
    },
    {
        "name": "ppt_agent_clone_plan",
        "description": (
            "Clone route, step 1: inspect a template -- shells by role, per-page-kind "
            "DNA counts and layer-stack summaries (the ornaments a build must inherit "
            "rather than redraw), plus the valid roles and kits for clone_build."
        ),
        "inputSchema": _schema(
            {"template": {"type": "string", "description": "Path to the template PPTX"}},
            ["template"],
        ),
    },
    {
        "name": "ppt_agent_clone_build",
        "description": (
            "Clone route, step 2: render a JSON page plan through the template's own "
            "shells -- untouched photos / logos / freeforms stay byte-identical -- then "
            "audit the result. Cover/closing rebuild their chrome; section/toc inherit "
            "the layout band; content pages dispatch to the named page kit."
        ),
        "inputSchema": _schema(
            {
                "template": {"type": "string", "description": "Path to the template PPTX"},
                "pages": _PROP_CLONE_PAGES,
                "output": {"type": "string", "description": "Destination .pptx path inside the workspace"},
                "audit": {"type": "boolean", "description": "Run audit_pages over the result (default true)"},
            },
            ["template", "pages", "output"],
        ),
    },
    {
        "name": "ppt_agent_clone_audit",
        "description": (
            "Clone route, step 3: run the six-kind page audit (overflow / collision / "
            "empty / duplicate / doubling / stale_placeholder) over any deck."
        ),
        "inputSchema": _schema(
            {"pptx": {"type": "string", "description": "Path to the deck to audit"}},
            ["pptx"],
        ),
    },
    {
        "name": "ppt_agent_fidelity_extract",
        "description": (
            "Fidelity engine: extract the hardened OOXML fidelity DNA of one slide "
            "(page kind, global render order, resolved styles/typography/tables/"
            "connectors, inheritance chains). The full DNA (raw XML evidence) is "
            "written to 'output' when given."
        ),
        "inputSchema": _schema(
            {
                "source": {"type": "string", "description": "Path to the PPTX"},
                "slide": {"type": "integer", "description": "1-based slide index (default 1)"},
                "output": {"type": "string", "description": "Optional path for the full DNA JSON"},
            },
            ["source"],
        ),
    },
    {
        "name": "ppt_agent_fidelity_diff",
        "description": (
            "Fidelity engine: matching-based structural diff of one slide between two "
            "decks, classified with the diff taxonomy (layer/geometry/style/text/media/"
            "inheritance/structure codes) plus semantic XML hashes."
        ),
        "inputSchema": _schema(
            {
                "reference": {"type": "string"},
                "candidate": {"type": "string"},
                "slide": {"type": "integer", "description": "1-based slide index (default 1)"},
                "tolerance": {"type": "number"},
                "output": {"type": "string", "description": "Optional path for the full report JSON"},
            },
            ["reference", "candidate"],
        ),
    },
    {
        "name": "ppt_agent_fidelity_repair",
        "description": (
            "Fidelity engine: iteratively repair a candidate deck against a reference "
            "(structural diff -> property-level OOXML repair -> re-extract -> re-diff; "
            "max_iterations default 3). Writes the repaired deck to 'output' and returns "
            "the loop payload including remaining issues and oscillation reports."
        ),
        "inputSchema": _schema(
            {
                "reference": {"type": "string"},
                "candidate": {"type": "string"},
                "output": {"type": "string", "description": "Destination .pptx path for the repaired deck"},
                "workspace": {"type": "string"},
                "max_iterations": {"type": "integer"},
                "render": {"type": "boolean", "description": "Run the visual gate once the structure matches"},
            },
            ["reference", "candidate", "output"],
        ),
    },
    {
        "name": "ppt_agent_fidelity_validate",
        "description": (
            "Fidelity engine: structural gate + rendered visual comparison. Renderer "
            "unavailability and renderer errors are reported explicitly and never "
            "downgraded to a pass."
        ),
        "inputSchema": _schema(
            {
                "reference": {"type": "string"},
                "candidate": {"type": "string"},
                "workspace": {"type": "string"},
                "render": {"type": "boolean", "description": "Default true"},
                "ssim": {"type": "number"},
                "mae": {"type": "number"},
                "mismatch": {"type": "number"},
                "output": {"type": "string", "description": "Optional path for the report JSON"},
            },
            ["reference", "candidate"],
        ),
    },
    {
        "name": "ppt_agent_narrative_plan",
        "description": (
            "Narrative planning over Markdown content. When the host declared MCP "
            "sampling support the section arc is planned by the host model "
            "(metadata.llm = sampled); otherwise the deterministic rules engine "
            "runs (llm = off), and if sampling fails the rules engine takes over "
            "with llm = fallback. Degradation is never silent."
        ),
        "inputSchema": _schema(
            {
                "markdown": {"type": "string", "description": "Inline Markdown content"},
                "source": {"type": "string", "description": "Path to a Markdown file"},
            },
        ),
    },
]


def list_tools() -> list[dict[str, Any]]:
    return [dict(spec) for spec in TOOL_SPECS]


def tool_names() -> list[str]:
    return [spec["name"] for spec in TOOL_SPECS]


def call_tool(name: str, arguments: dict[str, Any] | None, context: ToolContext) -> dict[str, Any]:
    """Execute a tool and shape the MCP tool result."""
    implementation = TOOL_IMPLEMENTATIONS.get(name)
    if implementation is None:
        raise JsonRpcError(INVALID_PARAMS, f"unknown tool: {name}")
    payload = arguments or {}
    if not isinstance(payload, dict):
        raise JsonRpcError(INVALID_PARAMS, "tool arguments must be an object")
    try:
        result = implementation(payload, context)
    except ToolError as exc:
        return _tool_result({"error": str(exc), "tool": name}, is_error=True)
    except JsonRpcError:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a tool failure
        return _tool_result({"error": f"{type(exc).__name__}: {exc}", "tool": name}, is_error=True)
    return _tool_result(result)


def _tool_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
        "isError": is_error,
    }
