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
from ..llm.provider import probe_vision_capability
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


# --- argument helpers -----------------------------------------------------
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


def _v3_sources(arguments: dict[str, Any], context: ToolContext) -> list[Path]:
    if isinstance(arguments.get("sources"), list):
        return [context.input_path(str(item)) for item in arguments["sources"]]
    return [context.input_path(_string(arguments, "source"))]


def _v3_task(arguments: dict[str, Any]) -> dict[str, Any]:
    task = arguments.get("task")
    if task is not None and not isinstance(task, dict):
        raise ToolError("'task' must be an object")
    return task or {}


def _v3_outline(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    path = context.input_path(_string(arguments, "outline_path"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ToolError("outline JSON must be an object")
    return payload


def _stage_output(payload: dict[str, Any], arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    output = _optional_string(arguments, "output")
    if not output:
        return payload
    target = context.output_path(output)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**payload, "output_path": str(target)}


def tool_analyze_sources(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    from ..pipeline import analyze_sources

    return _stage_output(
        analyze_sources(_v3_sources(arguments, context), task=_v3_task(arguments)),
        arguments,
        context,
    )


def tool_plan_outline(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    from ..pipeline import plan_outline_stage

    return _stage_output(
        plan_outline_stage(_v3_sources(arguments, context), task=_v3_task(arguments)),
        arguments,
        context,
    )


def tool_validate_outline(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    from ..pipeline import evaluate_outline_stage

    return _stage_output(
        evaluate_outline_stage(
            _v3_sources(arguments, context),
            _v3_outline(arguments, context),
            task=_v3_task(arguments),
        ),
        arguments,
        context,
    )


def tool_author_slides(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    from ..pipeline import author_slides_stage

    return _stage_output(
        author_slides_stage(_v3_sources(arguments, context), task=_v3_task(arguments)),
        arguments,
        context,
    )


def tool_list_builtin_templates(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    from ..pipeline import list_builtin_templates

    return _stage_output(list_builtin_templates(), arguments, context)


def tool_select_template(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    from ..pipeline import select_template_stage

    template = _optional_string(arguments, "template")
    template_path = context.input_path(template) if template and template.lower().endswith(".pptx") else None
    task = _v3_task(arguments)
    if template and not template.lower().endswith(".pptx"):
        task.setdefault("template", template)
    return _stage_output(
        select_template_stage(task, template_path=template_path),
        arguments,
        context,
    )


def tool_compile_page_design(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    from ..pipeline import compile_page_design_stage

    template = _optional_string(arguments, "template")
    template_path = context.input_path(template) if template and template.lower().endswith(".pptx") else None
    task = _v3_task(arguments)
    if template and not template.lower().endswith(".pptx"):
        task.setdefault("template", template)
    return _stage_output(
        compile_page_design_stage(
            _v3_sources(arguments, context),
            task=task,
            template_path=template_path,
        ),
        arguments,
        context,
    )


def tool_evaluate_deck(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    from ..pipeline import evaluate_outline_stage

    return _stage_output(
        evaluate_outline_stage(
            _v3_sources(arguments, context),
            _v3_outline(arguments, context),
            task=_v3_task(arguments),
        ),
        arguments,
        context,
    )


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


def tool_audit_editability(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    from ..editability import audit_pptx_editability

    deck = context.input_path(_string(arguments, "pptx"))
    template = _optional_string(arguments, "template")
    template_path = context.input_path(template) if template else None
    return audit_pptx_editability(deck, template=str(template_path) if template_path else None)


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
    from ..llm.provider import llm_fn_from_provider, resolve_provider
    from ..narrative_engine import build_narrative
    from ..parsers import parse_markdown

    text = _read_text(arguments, context, source_key="source", inline_key="markdown")
    document = parse_markdown(text)
    provider, provider_warning = resolve_provider(context.session)
    if provider is None:
        narrative = build_narrative(document)
    else:
        narrative = build_narrative(document, llm_fn=llm_fn_from_provider(provider))
    narrative["source"] = "mcp"
    if provider_warning:
        narrative["provider_warning"] = provider_warning
    return narrative


def tool_generate(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    from ..agent.pipeline import run_pipeline
    from ..llm.provider import llm_fn_from_provider, resolve_provider
    from ..visual_critic import ModelVisualCritic

    text = _read_text(arguments, context, source_key="source", inline_key="markdown")
    out_dir = _optional_string(arguments, "out_dir") or "pipeline"
    density = (_optional_string(arguments, "density") or "standard").lower()
    if density not in ("compact", "standard", "air"):
        raise ToolError("'density' must be compact, standard or air")
    task_spec = arguments.get("task_spec")
    if task_spec is not None and not isinstance(task_spec, dict):
        raise ToolError("'task_spec' must be an object")
    task_spec = dict(task_spec or {})
    user_request = _optional_string(arguments, "user_request")
    if user_request:
        task_spec["user_request"] = user_request
    provider, provider_warning = resolve_provider(context.session)
    llm_fn = llm_fn_from_provider(provider) if provider is not None else None
    visual_critic = None
    if provider is not None and getattr(provider, "supports_vision", False):
        vision_ok, vision_detail = probe_vision_capability(provider)
        if vision_ok:
            visual_critic = ModelVisualCritic(provider)
            visual_review_reason = None
        else:
            visual_review_reason = (
                "模型虽声明支持图像输入，但视觉能力探测未通过；"
                f"Agent 不会发送页面截图。原因：{vision_detail}"
            )
    elif provider is None:
        visual_review_reason = (
            f"{provider_warning} " if provider_warning else ""
        ) + (
            "当前没有可用模型；将只运行 Agent 可用的确定性检查，"
            "无法完整判断页面审美与视觉表达。"
        )
    elif getattr(provider, "name", "") == "mcp-sampling":
        if getattr(context.session, "vision_supported", None) is False:
            visual_review_reason = (
                "当前模型声明不支持图像输入；将退回确定性检查，"
                "无法完整判断页面审美与视觉表达。"
            )
        else:
            visual_review_reason = (
                "宿主未声明当前模型具备视觉能力；Agent 不会发送页面截图，"
                "将退回确定性检查，无法完整判断页面审美与视觉表达。"
            )
    else:
        visual_review_reason = (
            "当前接入仅配置了文本模型，未配置视觉模型；Agent 未向模型发送页面截图；"
            "将退回确定性检查，无法完整判断页面审美与视觉表达。"
        )
    result = run_pipeline(
        text,
        out_dir=context.output_path(out_dir),
        density=density,
        llm_fn=llm_fn,
        task_spec=task_spec,
        visual_critic=visual_critic,
        visual_review_reason=visual_review_reason,
        template_path=(
            context.input_path(_string(arguments, "template"))
            if _optional_string(arguments, "template") else None
        ),
        reference_html_path=(
            context.input_path(_string(arguments, "reference_html"))
            if _optional_string(arguments, "reference_html") else None
        ),
        reference_pdf_path=(
            context.input_path(_string(arguments, "reference_pdf"))
            if _optional_string(arguments, "reference_pdf") else None
        ),
    )
    if provider_warning:
        result.setdefault("metadata", {})["provider_warning"] = provider_warning
    return result


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
    "ppt_agent_audit_editability": tool_audit_editability,
    "ppt_agent_fidelity_extract": tool_fidelity_extract,
    "ppt_agent_fidelity_diff": tool_fidelity_diff,
    "ppt_agent_fidelity_repair": tool_fidelity_repair,
    "ppt_agent_fidelity_validate": tool_fidelity_validate,
    "ppt_agent_narrative_plan": tool_narrative_plan,
    "ppt_agent_generate": tool_generate,
    "ppt_agent_analyze_sources": tool_analyze_sources,
    "ppt_agent_plan_outline": tool_plan_outline,
    "ppt_agent_validate_outline": tool_validate_outline,
    "ppt_agent_author_slides": tool_author_slides,
    "ppt_agent_list_builtin_templates": tool_list_builtin_templates,
    "ppt_agent_select_template": tool_select_template,
    "ppt_agent_compile_page_design": tool_compile_page_design,
    "ppt_agent_evaluate_deck": tool_evaluate_deck,
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

_PROP_V3_TASK = {
    "type": "object",
    "description": "Audience, objective, tone, page budget, template preference and constraints",
}
_PROP_V3_SOURCE = {"type": "string", "description": "Path to a supported source file"}
_PROP_V3_SOURCES = {
    "type": "array",
    "description": "Paths to Markdown, DOCX, PPTX, PDF, HTML or image sources",
    "items": {"type": "string"},
}
_PROP_V3_TEMPLATE = {
    "type": "string",
    "description": "Built-in template id or path to a user .pptx template",
}
_PROP_V3_OUTLINE_PATH = {"type": "string", "description": "Path to outline JSON"}

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
        "name": "ppt_agent_audit_editability",
        "description": (
            "Editability gate: verify that every page has native editable "
            "text, table, chart or shape content and that no post-build "
            "screenshot paste bypassed the editability rule. With a template "
            "reference, slide-local pictures not present in the template are "
            "flagged as violations."
        ),
        "inputSchema": _schema(
            {
                "pptx": {"type": "string", "description": "Path to the deck to audit"},
                "template": {"type": "string", "description": "Optional template PPTX for picture hash allow-listing"},
            },
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
    {
        "name": "ppt_agent_generate",
        "description": (
            "End-to-end: Markdown -> analyzed -> model-authored storyboard -> template-aware "
            "PPTX + HTML -> per-page delivery gate -> bounded source-preserving repair. "
            "The report states every stage's decision, the gate obligations and the "
            "honest model/vision fallback state."
        ),
        "inputSchema": _schema(
            {
                "markdown": {"type": "string", "description": "Inline Markdown content"},
                "source": {"type": "string", "description": "Path to a Markdown file"},
                "out_dir": {"type": "string", "description": "Output directory inside the workspace (default 'pipeline')"},
                "density": {"type": "string", "enum": ["compact", "standard", "air"]},
                "template": {"type": "string", "description": "Optional PPTX template path inside the workspace"},
                "reference_html": {"type": "string", "description": "Optional HTML reference with architecture diagrams and design context"},
                "reference_pdf": {"type": "string", "description": "Optional PDF content and visual reference; OCR text works without a declared vision model"},
                "user_request": {"type": "string", "description": "Original user brief, preserved as a planning constraint"},
                "task_spec": {
                    "type": "object",
                    "description": "Audience, objective, page budget and visual constraints for model-authored storyboarding",
                },
            },
        ),
    },
    {
        "name": "ppt_agent_analyze_sources",
        "description": "V3 stage 1: ingest multiple sources into SourcePack, EvidenceGraph and ContentRelations.",
        "inputSchema": _schema({
            "source": _PROP_V3_SOURCE,
            "sources": _PROP_V3_SOURCES,
            "task": _PROP_V3_TASK,
            "output": {"type": "string"},
        }),
    },
    {
        "name": "ppt_agent_plan_outline",
        "description": "V3 stage 2: create and validate a provenance-first outline.",
        "inputSchema": _schema({
            "source": _PROP_V3_SOURCE,
            "sources": _PROP_V3_SOURCES,
            "task": _PROP_V3_TASK,
            "output": {"type": "string"},
        }),
    },
    {
        "name": "ppt_agent_validate_outline",
        "description": "V3 stage 3: validate page purposes, evidence IDs, source coverage and page budget.",
        "inputSchema": _schema({
            "source": _PROP_V3_SOURCE,
            "sources": _PROP_V3_SOURCES,
            "outline_path": _PROP_V3_OUTLINE_PATH,
            "task": _PROP_V3_TASK,
            "output": {"type": "string"},
        }, ["outline_path"]),
    },
    {
        "name": "ppt_agent_author_slides",
        "description": "V3 stage 4: turn an outline into SlideSpec contracts with traceable evidence.",
        "inputSchema": _schema({
            "source": _PROP_V3_SOURCE,
            "sources": _PROP_V3_SOURCES,
            "task": _PROP_V3_TASK,
            "output": {"type": "string"},
        }),
    },
    {
        "name": "ppt_agent_list_builtin_templates",
        "description": "List the built-in, self-owned template catalog.",
        "inputSchema": _schema({"output": {"type": "string"}}),
    },
    {
        "name": "ppt_agent_select_template",
        "description": "Resolve a user PPTX template or score and select a built-in template profile.",
        "inputSchema": _schema({
            "task": _PROP_V3_TASK,
            "template": _PROP_V3_TEMPLATE,
            "output": {"type": "string"},
        }),
    },
    {
        "name": "ppt_agent_compile_page_design",
        "description": "V3 stage 5: compile validated SlideSpecs and a resolved template into Page Design IR.",
        "inputSchema": _schema({
            "source": _PROP_V3_SOURCE,
            "sources": _PROP_V3_SOURCES,
            "task": _PROP_V3_TASK,
            "template": _PROP_V3_TEMPLATE,
            "output": {"type": "string"},
        }),
    },
    {
        "name": "ppt_agent_evaluate_deck",
        "description": "Evaluate an outline and deck evidence against source provenance and page budget.",
        "inputSchema": _schema({
            "source": _PROP_V3_SOURCE,
            "sources": _PROP_V3_SOURCES,
            "outline_path": _PROP_V3_OUTLINE_PATH,
            "task": _PROP_V3_TASK,
            "output": {"type": "string"},
        }, ["outline_path"]),
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
