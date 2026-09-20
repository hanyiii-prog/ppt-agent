"""The V2.2 end-to-end pipeline: every layer, one honest report.

``run_pipeline(markdown, *, out_dir)`` runs:

Input -> Parse -> Analyze -> Narrative -> Plan -> Archetypes -> Fidelity Mode
-> Plan-to-IR (kind-aware DNA + element cache + solver geometry)
-> Render (native PPTX + HTML preview) -> QA Gate -> Post-render Repair
-> Deliver.

V2.2 additions over V2.1:
* per-page-kind DNA drives backgrounds, fonts, colours per page kind;
* element store caches generated elements (hit rate reported, tokens saved);
* component store provides reusable multi-element controls;
* template fingerprint consistency check (never mix templates);
* post-render repair round (after python-pptx autofit may shift things);
* rasterizer detection (visual regression upgrades from degraded);
* design rules validation when a rulebook is available.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..component_matcher import match_components
from ..component_store import list_components
from ..content_analyzer import analyze_content
from ..fidelity_mode import gates_report, resolve_fidelity_mode
from ..narrative_engine import build_narrative
from ..page_archetype import annotate_plan
from ..page_kind_dna import build_page_kind_dna
from ..parsers import parse_markdown
from ..presentation_plan import build_presentation_plan
from ..repair import run_repair_cycle
from ..template_fingerprint import check_template_consistency
from ..element_store import stats as element_stats
from ..sdk import PptAgent
from .plan_to_ir import plan_to_ir

SCHEMA = "pipeline/v2"


def _component_boxes(presentation: Any) -> list[dict[str, Any]]:
    boxes: list[dict[str, Any]] = []
    for slide in presentation.slides:
        for component in slide.components:
            boxes.append({
                "x": component.x or 0.0, "y": component.y or 0.0,
                "w": component.w or 0.05, "h": component.h or 0.05,
                "absolute": True,
                "text": component.text or "",
            })
    return boxes


def _detect_rasterizer() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def run_pipeline(
    markdown: str,
    *,
    out_dir: str | Path,
    density: str = "standard",
    engine: str = "solver",
    llm_fn: Callable[[str], str] | None = None,
    agent: PptAgent | None = None,
    gate_deck: bool = True,
    template_dna: dict[str, Any] | None = None,
    design_dna: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Markdown -> delivered deck + the full decision report."""
    agent = agent or PptAgent()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # template consistency check (V2.2: never mix templates)
    fingerprint = ""
    if design_dna is not None:
        fingerprint = check_template_consistency(design_dna, template_dna or {})

    # 1-2. parse + analyze
    document = parse_markdown(markdown, source="pipeline")
    analyzed = analyze_content(document)

    # 3. narrative (the only stage that may touch a model via llm_fn)
    narrative = build_narrative(analyzed, llm_fn=llm_fn)

    # 4. plan + archetypes
    plan = build_presentation_plan(analyzed, density=density)
    annotated = annotate_plan(plan, analyzed)

    # 5. fidelity mode
    mode_report = resolve_fidelity_mode("designed", template_dna=template_dna)

    # 5.5 page-kind DNA (V2.2: per-kind styling)
    kind_dna = build_page_kind_dna(template_dna or {}, design_dna or {}, template_fingerprint=fingerprint) if template_dna else None

    # 6. plan -> IR with solver geometry + element cache (V2.2)
    presentation, element_cache = plan_to_ir(
        annotated, analyzed, title=document.title,
        page_kind_dna=kind_dna, llm_fn=llm_fn,
        template_fingerprint=fingerprint, layout_engine=engine,
    )

    # 7. pre-render repair cycle
    boxes = _component_boxes(presentation)
    repair_report = run_repair_cycle(boxes, 13.333, 7.5)

    # 8. render native pptx + html preview
    pptx_path = out / "deck.pptx"
    render_result = agent.render(presentation, pptx_path).to_dict()
    html_path = out / "deck.html"
    html_result = agent.render(presentation, html_path, renderer="html").to_dict()

    # 8.5 post-render repair (V2.2: re-extract geometry from the rendered deck)
    if gate_deck and pptx_path.exists():
        try:
            from ..page_validation import audit_page
            audit_result = audit_page(str(pptx_path), 1)
            post_issues = (audit_result or {}).get("issues") or []
            if post_issues:
                post_boxes = [
                    {"x": i.get("x", 0), "y": i.get("y", 0), "w": i.get("w", 1), "h": i.get("h", 1),
                     "absolute": True, "text": i.get("text", "")}
                    for i in post_issues if isinstance(i, dict)
                ]
                post_repair = run_repair_cycle(post_boxes, 13.333, 7.5)
                repair_report["post_render"] = {
                    "issues_found": len(post_issues),
                    "stop_reason": post_repair["stop_reason"],
                    "residual_count": post_repair["residual_count"],
                }
        except Exception:
            repair_report["post_render"] = {"status": "unavailable"}

    # 9. QA gate on the rendered deck
    gate_report = agent.gate(pptx_path, workspace=out / "qa") if gate_deck else {
        "passed": None, "mode": "skipped",
    }

    # component matching with the real store (V2.2: not always empty)
    stored_components = list_components()
    component_library = {"components": stored_components} if stored_components else {"components": []}
    component_matches = match_components(component_library, analyzed)

    # design rules validation (V2.2: wired when a rulebook is available)
    design_rules_findings: list[dict[str, Any]] = []
    has_design_rules = False
    if design_dna:
        try:
            from ..design_rules import build_design_rules, validate_design
            rules = build_design_rules(design_dna)
            findings = validate_design(design_dna, rules)
            design_rules_findings = findings
            has_design_rules = True
        except Exception:
            pass

    has_rasterizer = _detect_rasterizer()

    return {
        "schema": SCHEMA,
        "title": presentation.title,
        "page_total": len(presentation.slides),
        "template_fingerprint": fingerprint or None,
        "stages": {
            "parse": {"format": document.format, "blocks": len(document.blocks)},
            "analyze": {"analyzer": analyzed.metadata.get("analyzer")},
            "narrative": {"mode": narrative["mode"], "arc": narrative["arc"]},
            "plan": {"page_total": plan["page_total"],
                     "estimate_delta": plan["estimate_reference"]["delta_vs_plan"]},
            "archetypes": {
                page["page_no"]: (page.get("archetype") or {}).get("archetype")
                for page in annotated["pages"] if page["kind"] == "content"
            },
            "fidelity": {"mode": mode_report["mode"], "basis": mode_report["basis"]},
            "repair": {"stop_reason": repair_report["stop_reason"],
                       "residual_count": repair_report["residual_count"],
                       "post_render": repair_report.get("post_render")},
        },
        "element_cache": {
            **element_cache,
            "store_stats": element_stats(),
        },
        "component_matches": component_matches,
        "design_rules": {
            "has_rules": has_design_rules,
            "findings": design_rules_findings,
            "finding_count": len(design_rules_findings),
        },
        "artifacts": {
            "pptx": render_result.get("path") or str(pptx_path),
            "html": html_result.get("path") or str(html_path),
        },
        "gates": {
            "fidelity_report": gates_report(
                "designed", has_design_rules=has_design_rules, has_rasterizer=has_rasterizer
            ),
            "delivery": gate_report,
        },
        "metadata": {"llm": narrative["metadata"]["llm"], "pipeline": "rules+solver+cache"},
    }
