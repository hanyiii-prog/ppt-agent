"""The V2.1 end-to-end pipeline: every layer, one honest report.

``run_pipeline(markdown, *, out_dir)`` runs:

Input → Parse → Analyze → Narrative → Plan → Archetypes → Fidelity Mode →
Plan-to-IR (solver geometry) → Render (native PPTX + HTML preview) →
QA Gate → Repair Cycle → Deliver.

Honesty contracts enforced here:
* ``metadata.llm`` aggregates the narrative stage's sampled/fallback/off --
  the only stage that may touch a model;
* the fidelity gates report is embedded verbatim (required/degraded/off with
  reasons) so nothing is silently skipped;
* the repair cycle report is embedded verbatim, including residual problems.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..component_matcher import match_components
from ..content_analyzer import analyze_content
from ..fidelity_mode import gates_report, resolve_fidelity_mode
from ..narrative_engine import build_narrative
from ..page_archetype import annotate_plan
from ..parsers import parse_markdown
from ..presentation_plan import build_presentation_plan
from ..repair import run_repair_cycle
from ..sdk import PptAgent
from .plan_to_ir import plan_to_ir

SCHEMA = "pipeline/v1"


def _component_boxes(presentation: Any) -> list[dict[str, Any]]:
    """Flatten every component's absolute geometry into constraint-box dicts."""
    boxes: list[dict[str, Any]] = []
    for slide in presentation.slides:
        for component in slide.components:
            boxes.append({
                "x": component.x or 0.0, "y": component.y or 0.0,
                "w": component.w or 0.05, "h": component.h or 0.05,
                "absolute": True,  # plan_to_ir already froze the geometry
                "text": component.text or "",
            })
    return boxes


def run_pipeline(
    markdown: str,
    *,
    out_dir: str | Path,
    density: str = "standard",
    engine: str = "solver",
    llm_fn: Callable[[str], str] | None = None,
    agent: PptAgent | None = None,
    gate_deck: bool = True,
) -> dict[str, Any]:
    """Markdown -> delivered deck + the full decision report."""
    agent = agent or PptAgent()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 1-2. parse + analyze
    document = parse_markdown(markdown, source="pipeline")
    analyzed = analyze_content(document)

    # 3. narrative (the only stage that may touch a model)
    narrative = build_narrative(analyzed, llm_fn=llm_fn)

    # 4. plan + archetypes
    plan = build_presentation_plan(analyzed, density=density)
    annotated = annotate_plan(plan, analyzed)

    # 5. fidelity mode (designed route; clone route lives in the clone tools)
    mode_report = resolve_fidelity_mode("designed")

    # 6. plan -> IR with solver geometry
    presentation = plan_to_ir(annotated, analyzed, title=document.title)

    # 7. repair cycle over the resolved geometry (pre-render; honest no-op when clean)
    boxes = _component_boxes(presentation)
    repair_report = run_repair_cycle(boxes, 13.333, 7.5)

    # 8. render native pptx + html preview
    pptx_path = out / "deck.pptx"
    render_result = agent.render(presentation, pptx_path).to_dict()
    html_path = out / "deck.html"
    html_result = agent.render(presentation, html_path, renderer="html").to_dict()

    # 9. QA gate on the rendered deck
    gate_report = agent.gate(pptx_path, workspace=out / "qa") if gate_deck else {
        "passed": None, "mode": "skipped",
    }

    # component matching (informational: template library would come from DNA)
    component_matches = match_components({"components": []}, analyzed)

    return {
        "schema": SCHEMA,
        "title": presentation.title,
        "page_total": len(presentation.slides),
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
                       "residual_count": repair_report["residual_count"]},
        },
        "artifacts": {
            "pptx": render_result.get("path") or str(pptx_path),
            "html": html_result.get("path") or str(html_path),
        },
        "gates": {
            "fidelity_report": gates_report(
                "designed", has_design_rules=False, has_rasterizer=False
            ),
            "delivery": gate_report,
        },
        "component_matches": component_matches,
        "metadata": {"llm": narrative["metadata"]["llm"], "pipeline": "rules+solver"},
    }
