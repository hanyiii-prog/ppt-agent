from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Sequence

from .composition_compiler import compile_presentation
from .content_relations import build_content_relations
from .deck_brief import DeckBrief
from .deck_evaluator import evaluate_deck
from .evidence_graph import build_evidence_graph
from .ir import Presentation
from .outline_planner import plan_outline, validate_outline_with_model
from .outline_validator import validate_outline
from .page_design_ir import build_page_design_ir
from .quality_report import build_final_report
from .repair_loop import apply_repair_requests, repair_and_rebuild
from .slide_author import author_slide_specs
from .source_pack import build_source_pack
from .template_profile import user_template_page_plan
from .template_selector import select_template


def run_v3_pipeline(
    source: str | Path,
    output: str | Path,
    *,
    task: dict[str, Any] | None = None,
    llm_fn: Callable[[str], str] | None = None,
    visual_critic: Any | None = None,
    visual_review_reason: str | None = None,
    max_repair_iterations: int = 3,
    template_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the full V3 provenance-first pipeline and write every stage."""
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    brief = DeckBrief.from_task(task or {})
    document, pack = build_source_pack(source, source_priority=brief.source_priority)
    evidence = build_evidence_graph(pack)
    outline = plan_outline(document, pack, brief, llm_fn=llm_fn)
    _normalise_outline_evidence(outline, evidence, pack)
    errors = validate_outline(outline, pack, brief, evidence=evidence)
    if errors:
        raise ValueError("; ".join(errors))
    outline_review: dict[str, Any] = {
        "schema": "outline-review/v1",
        "passed": True,
        "issues": [],
        "warning": "No content model was supplied; outline review was deterministic.",
    }
    if llm_fn is not None:
        outline_review = validate_outline_with_model(outline, pack, brief, llm_fn=llm_fn)
        if not outline_review.get("passed"):
            outline = plan_outline(document, pack, brief, llm_fn=llm_fn)
            _normalise_outline_evidence(outline, evidence, pack)
            errors = validate_outline(outline, pack, brief, evidence=evidence)
            if errors:
                raise ValueError("; ".join(errors))
            outline_review = validate_outline_with_model(
                outline, pack, brief, llm_fn=llm_fn
            )
    specs = author_slide_specs(outline, pack, evidence, llm_fn=llm_fn)
    template = _resolve_template(brief, template_path)
    design_ir = build_page_design_ir(outline, template, specs)
    design_ir["title"] = outline.title
    final_pptx_path = out / "deck.pptx"
    html_path = out / "deck.html"
    user_template_result: dict[str, Any] | None = None
    template_route = "builtin-composition"

    def build(iteration: int, repair_requests: list[dict[str, Any]]) -> Path:
        current_ir = design_ir if iteration == 1 else apply_repair_requests(design_ir, repair_requests)
        current_deck = compile_presentation(current_ir, evidence)
        path = out / f"deck-iteration-{iteration}.pptx"
        from .renderers import render_with

        render_with(current_deck, path)
        return path

    if template_path is not None:
        template_route = "user-template-clone-shell"
        from .clone_build import render_clone_deck
        from .delivery import validate_delivery
        from .dna_to_ir import template_dna_to_ir
        from .template import analyze_pptx

        user_template_result = render_clone_deck(
            Path(template_path),
            user_template_page_plan(specs),
            final_pptx_path,
        )
        current_deck = template_dna_to_ir(
            analyze_pptx(final_pptx_path), source=str(template_path)
        )
        page_gate, critic_gate, visual_gate = validate_delivery(
            final_pptx_path,
            out / "quality" / "user-template",
            critic=visual_critic,
            visual_review_reason=visual_review_reason,
        )
        template_passed = bool(
            (user_template_result.get("audit") or {}).get("count") == 0
            and (user_template_result.get("fidelity") or {}).get("passed")
            and page_gate.passed
            and critic_gate.passed
            and (visual_gate is None or visual_gate.passed)
        )
        delivery = {
            "passed": template_passed,
            "final_pptx": str(final_pptx_path),
            "attempts": [{
                "iteration": 1,
                "pptx": str(final_pptx_path),
                "page_gate_passed": page_gate.passed,
                "critic_gate_passed": critic_gate.passed,
                "visual_gate_passed": visual_gate.passed if visual_gate else None,
                "repair_requests": [],
                "template_route": template_route,
            }],
            "page_gate": page_gate.to_dict(),
            "critic_gate": critic_gate.to_dict(),
            "visual_gate": visual_gate.to_dict() if visual_gate else None,
        }
        _write_json(out / "quality" / "user-template" / "delivery-report.json", delivery)
        quality_extra = {
            "template_route": template_route,
            "clone_audit": user_template_result.get("audit"),
            "clone_fidelity": user_template_result.get("fidelity"),
            "structural_qc": user_template_result.get("structural_qc"),
        }
    else:
        delivery = repair_and_rebuild(
            build,
            workspace=out / "quality" / "repair",
            critic=visual_critic,
            visual_review_reason=visual_review_reason,
            max_iterations=max_repair_iterations,
        )
        final_pptx = Path(delivery["final_pptx"])
        final_pptx_path.write_bytes(final_pptx.read_bytes())
        attempts = delivery.get("attempts") or []
        current_ir = (
            design_ir
            if not attempts or len(attempts) == 1
            else apply_repair_requests(design_ir, attempts[-1].get("repair_requests") or [])
        )
        current_deck = compile_presentation(current_ir, evidence)
        quality_extra = {"template_route": template_route}
    from .renderers import render_with

    render_with(current_deck, html_path, renderer="html")
    quality = evaluate_deck(
        current_deck,
        outline,
        pack,
        evidence,
        {"pptx": str(final_pptx_path), "html": str(html_path)},
        planning_mode=outline.planning_mode,
        visual_report=delivery.get("critic_gate"),
    )
    quality.update(quality_extra)
    quality["visual_quality"].setdefault("model_review", (
        "used" if (delivery.get("critic_gate") or {}).get("mode") == "model" else "unavailable"
    ))
    if not delivery.get("passed"):
        quality["status"] = "failed"
    quality["render"] = {
        "pptx_written": final_pptx_path.is_file(),
        "html_written": html_path.is_file(),
        "error": None,
    }
    report = build_final_report(
        quality,
        template,
        {"mode": outline.planning_mode, "outline_review": outline_review},
        degradations=_degradations(visual_critic, visual_review_reason, delivery),
        repairs=delivery.get("attempts") or [],
        artifacts={"pptx": str(final_pptx_path), "html": str(html_path)},
        template_route=template_route,
    )
    _write_json(out / "source-pack.json", pack.to_dict())
    _write_json(out / "evidence-graph.json", evidence.to_dict())
    _write_json(out / "deck-brief.json", brief.to_dict())
    _write_json(out / "outline.json", outline.to_dict())
    _write_json(out / "outline-review.json", outline_review)
    _write_json(out / "slide-specs.json", [spec.to_dict() for spec in specs])
    _write_json(out / "template-profile.json", template)
    _write_json(out / "composition-plan.json", _composition_plan(design_ir))
    _write_json(out / "page-design-ir.json", design_ir)
    _write_json(out / "quality" / "structural.json", quality["structural_quality"])
    _write_json(out / "quality" / "facts.json", quality["content_quality"])
    _write_json(out / "quality" / "visual.json", quality["visual_quality"])
    _write_json(out / "quality" / "final-report.json", report)
    _write_json(out / "final-report.json", report)
    _write_json(out / "manifest.json", {
        "schema": "v3-manifest/v1",
        "status": report["status"],
        "artifacts": report["artifacts"],
        "page_total": report["page_total"],
    })
    return report


def _resolve_template(
    brief: DeckBrief,
    template_path: str | Path | None,
) -> dict[str, Any]:
    if template_path is not None:
        from .template import analyze_pptx
        from .template_profile import profile_from_template_dna

        return profile_from_template_dna(analyze_pptx(Path(template_path)), template_path)
    return select_template(brief)


def _normalise_outline_evidence(outline: Any, evidence: Any, pack: Any = None) -> None:
    """Convert block references into stable EvidenceGraph fact IDs."""
    facts = evidence.facts if hasattr(evidence, "facts") else (evidence or {}).get("facts") or []
    fact_by_block = {
        block_id: fact["id"]
        for fact in facts
        for block_id in fact.get("source_block_ids") or []
    }
    for slide in outline.slides if hasattr(outline, "slides") else outline.get("slides") or []:
        source_ids = {block["id"] for block in pack.blocks} if pack is not None else set()
        resolved_refs = []
        for ref in slide.get("source_block_ids") or []:
            ref = str(ref)
            if ref in source_ids or not source_ids:
                resolved_refs.append(ref)
                continue
            resolved = next((block["id"] for block in pack.blocks if block["id"].endswith(f"-{ref}") or block["id"].split("-", 1)[-1] == ref), ref)
            resolved_refs.append(resolved)
        slide["source_block_ids"] = list(dict.fromkeys(resolved_refs))
        slide["evidence_ids"] = list(dict.fromkeys(
            fact_by_block.get(ref, str(ref))
            for ref in resolved_refs
        ))


def _composition_plan(design_ir: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "composition-plan/v1",
        "pages": [
            {
                "page_id": page.get("page_id"),
                "template_family": page.get("template_family"),
                "composition": page.get("composition"),
                "visual_form": page.get("visual_form"),
            }
            for page in design_ir.get("pages") or []
        ],
    }


def _degradations(
    visual_critic: Any | None,
    visual_review_reason: str | None,
    delivery: dict[str, Any],
) -> list[str]:
    result: list[str] = []
    if visual_critic is None:
        result.append("visual_model: unavailable")
    if visual_review_reason:
        result.append(visual_review_reason)
    if not delivery.get("passed"):
        result.append("repair_loop: did not converge")
    return result


def load_presentation(path: str | Path) -> Presentation:
    from .ir import Presentation as P

    return P.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


__all__ = [
    "run_v3_pipeline",
    "analyze_sources",
    "plan_outline_stage",
    "author_slides_stage",
    "list_builtin_templates",
    "select_template_stage",
    "compile_page_design_stage",
    "evaluate_outline_stage",
]


def analyze_sources(
    source: str | Path | Sequence[str | Path],
    *,
    task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the source-understanding stage and return serializable contracts."""
    brief = DeckBrief.from_task(task or {})
    document, pack = build_source_pack(source, source_priority=brief.source_priority)
    evidence = build_evidence_graph(pack)
    fact_ids: dict[str, str] = {}
    for fact in evidence.facts:
        for block_id in fact.get("source_block_ids") or []:
            fact_ids[block_id] = fact["id"]
    relations = build_content_relations(pack, fact_ids)
    return {
        "schema": "source-analysis/v1",
        "document": {
            "title": document.title,
            "format": document.format,
            "block_count": len(document.blocks),
        },
        "deck_brief": brief.to_dict(),
        "source_pack": pack.to_dict(),
        "evidence_graph": evidence.to_dict(),
        "content_relations": relations,
    }


def plan_outline_stage(
    source: str | Path | Sequence[str | Path],
    *,
    task: dict[str, Any] | None = None,
    llm_fn: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Plan and validate an Outline without compiling slides."""
    brief = DeckBrief.from_task(task or {})
    document, pack = build_source_pack(source, source_priority=brief.source_priority)
    evidence = build_evidence_graph(pack)
    outline = plan_outline(document, pack, brief, llm_fn=llm_fn)
    _normalise_outline_evidence(outline, evidence)
    errors = validate_outline(outline, pack, brief, evidence=evidence)
    review = (
        validate_outline_with_model(outline, pack, brief, llm_fn=llm_fn)
        if llm_fn is not None
        else {
            "schema": "outline-review/v1", "passed": True, "issues": [],
            "warning": "No content model was supplied; outline review was deterministic.",
        }
    )
    return {
        "schema": "outline-stage/v1", "passed": not errors,
        "errors": errors, "outline": outline.to_dict(), "review": review,
    }


def author_slides_stage(
    source: str | Path | Sequence[str | Path],
    *,
    task: dict[str, Any] | None = None,
    llm_fn: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Author validated SlideSpecs from a source pack."""
    brief = DeckBrief.from_task(task or {})
    document, pack = build_source_pack(source, source_priority=brief.source_priority)
    evidence = build_evidence_graph(pack)
    outline = plan_outline(document, pack, brief, llm_fn=llm_fn)
    _normalise_outline_evidence(outline, evidence)
    errors = validate_outline(outline, pack, brief, evidence=evidence)
    if errors:
        raise ValueError("; ".join(errors))
    specs = author_slide_specs(outline, pack, evidence, llm_fn=llm_fn)
    return {
        "schema": "slide-spec-stage/v1",
        "outline": outline.to_dict(),
        "slide_specs": [spec.to_dict() for spec in specs],
    }


def list_builtin_templates() -> dict[str, Any]:
    from .template_library import builtin_templates

    return {
        "schema": "template-catalog/v1",
        "templates": list(builtin_templates().values()),
    }


def select_template_stage(
    task: dict[str, Any] | None = None,
    *,
    template_path: str | Path | None = None,
) -> dict[str, Any]:
    brief = DeckBrief.from_task(task or {})
    return _resolve_template(brief, template_path)


def compile_page_design_stage(
    source: str | Path | Sequence[str | Path],
    *,
    task: dict[str, Any] | None = None,
    llm_fn: Callable[[str], str] | None = None,
    template_path: str | Path | None = None,
) -> dict[str, Any]:
    """Resolve a template and compile validated SlideSpecs to Page Design IR."""
    brief = DeckBrief.from_task(task or {})
    document, pack = build_source_pack(source, source_priority=brief.source_priority)
    evidence = build_evidence_graph(pack)
    outline = plan_outline(document, pack, brief, llm_fn=llm_fn)
    _normalise_outline_evidence(outline, evidence)
    errors = validate_outline(outline, pack, brief, evidence=evidence)
    if errors:
        raise ValueError("; ".join(errors))
    specs = author_slide_specs(outline, pack, evidence, llm_fn=llm_fn)
    template = _resolve_template(brief, template_path)
    design_ir = build_page_design_ir(outline, template, specs)
    design_ir["title"] = outline.title
    return {
        "schema": "page-design-stage/v1",
        "template_profile": template,
        "outline": outline.to_dict(),
        "slide_specs": [spec.to_dict() for spec in specs],
        "page_design_ir": design_ir,
    }


def evaluate_outline_stage(
    source: str | Path | Sequence[str | Path],
    outline: dict[str, Any] | Any,
    *,
    task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    brief = DeckBrief.from_task(task or {})
    document, pack = build_source_pack(source, source_priority=brief.source_priority)
    evidence = build_evidence_graph(pack)
    errors = validate_outline(outline, pack, brief, evidence=evidence)
    return {
        "schema": "outline-validation/v1",
        "passed": not errors,
        "errors": errors,
    }
