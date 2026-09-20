"""The V2.2 end-to-end pipeline: every layer, one honest report.

Route resolution is automatic:
* ``template_dna`` provided -> **clone route** (template chrome inherited verbatim)
* ``template_dna`` absent   -> **designed route** (theme-driven from scratch)

The clone route converts the presentation plan into clone page specs and
calls ``clone_build.render_clone_deck`` -- the SAME code path the MCP tools
use. The output inherits every untouched decoration byte-identically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..content_analyzer import analyze_content
from ..narrative_engine import build_narrative
from ..page_archetype import annotate_plan
from ..parsers import parse_markdown
from ..presentation_plan import build_presentation_plan
from ..fidelity_mode import gates_report, resolve_fidelity_mode
from ..template_fingerprint import check_template_consistency
from ..sdk import PptAgent
from ..component_matcher import match_components
from ..component_store import list_components
from ..element_store import stats as element_stats

SCHEMA = "pipeline/v2"


def _detect_rasterizer() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


# ---- clone route helpers ------------------------------------------------

def _archetype_to_kit(archetype: str, item_count: int) -> str:
    """Map a content archetype to the best available clone kit."""
    from ..clone_build import KITS

    mapping = {
        "cards_grid": "four_role_cards",
        "metrics_row": "four_role_cards",
        "table_page": "n_column_cards",
        "timeline": "progress_timeline",
        "comparison": "two_panel_list",
        "quote_strip": "n_column_cards",
        "narrative": "n_column_cards",
        "title_bullets": "n_column_cards",
    }
    kit = mapping.get(archetype, "n_column_cards")
    if kit not in KITS:
        kit = "n_column_cards"
    return kit


def _plan_to_clone_pages(
    plan: dict[str, Any],
    document: Any,
) -> list[dict[str, Any]]:
    """Convert a presentation plan into clone-route page specs."""
    lookup = {block.id: block for block in document.blocks}
    section_titles = [
        str(page.get("title") or "")
        for page in plan.get("pages") or []
        if page.get("kind") == "section"
    ]

    pages: list[dict[str, Any]] = []
    for page in plan.get("pages") or []:
        kind = str(page.get("kind") or "content")
        archetype = (page.get("archetype") or {}).get("archetype") or "title_bullets"
        blocks = [lookup[bid] for bid in page.get("source_blocks") or [] if bid in lookup]

        if kind == "cover":
            pages.append({
                "role": "cover",
                "kit": "cover",
                "title": page.get("title") or document.title or "Presentation",
            })
        elif kind == "toc":
            pages.append({
                "role": "toc",
                "kit": "toc_page",
                "title": page.get("title") or "目录",
                "sections": [{"title": t} for t in section_titles],
            })
        elif kind == "section":
            pages.append({
                "role": "section",
                "kit": "section_divider",
                "title": page.get("title") or "",
            })
        elif kind == "closing":
            pages.append({
                "role": "closing",
                "kit": "closing_page",
                "title": "谢谢",
            })
        else:
            kit = _archetype_to_kit(archetype, len(blocks))
            spec: dict[str, Any] = {
                "role": "content",
                "kit": kit,
                "title": page.get("title") or "",
            }
            if archetype in ("cards_grid", "metrics_row"):
                spec["cards"] = _blocks_to_cards(blocks)
            elif archetype == "timeline":
                spec["steps"] = _blocks_to_steps(blocks)
            elif archetype == "comparison":
                spec["left"], spec["right"] = _blocks_to_comparison(blocks)
            elif blocks and blocks[0].type == "table":
                spec["table"] = {
                    "headers": blocks[0].headers,
                    "rows": blocks[0].rows,
                }
            else:
                spec["items"] = _blocks_to_items(blocks)
            pages.append(spec)

    return pages


def _blocks_to_cards(blocks: list) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    for block in blocks:
        if block.type in ("bullets", "ordered") and block.items:
            for item in block.items:
                title, _, body = item.partition("：") or item.partition(":")
                cards.append({"title": title.strip(), "body": body.strip() or title.strip()})
        elif block.text:
            title, _, body = block.text.partition("：") or block.text.partition(":")
            cards.append({"title": title.strip(), "body": body.strip() or title.strip()})
    return cards


def _blocks_to_steps(blocks: list) -> list[dict[str, str]]:
    import re
    steps: list[dict[str, str]] = []
    for block in blocks:
        if block.type in ("bullets", "ordered"):
            for item in block.items:
                match = re.match(r"^(.{1,12}?)[：:](.+)$", item)
                if match:
                    steps.append({"label": match.group(1).strip(), "detail": match.group(2).strip()})
                else:
                    steps.append({"label": item[:12], "detail": item})
        elif block.text:
            steps.append({"label": block.text[:12], "detail": block.text})
    return steps


def _blocks_to_comparison(blocks: list) -> tuple[list[str], list[str]]:
    left: list[str] = []
    right: list[str] = []
    target = left
    for block in blocks:
        text = block.text or ""
        items = block.items if block.type in ("bullets", "ordered") else [text]
        for item in items:
            if "vs" in item.lower() or "对比" in item or "相较" in item:
                target = right
                continue
            target.append(item)
    return left, right


def _blocks_to_items(blocks: list) -> list[str]:
    items: list[str] = []
    for block in blocks:
        if block.type in ("bullets", "ordered"):
            items.extend(block.items)
        elif block.text:
            items.append(block.text)
    return items



# ---- report helpers (these were dropped in the rewrite) ----

def _element_cache_for_report(route: str, artifacts: dict) -> dict:
    if route == "designed" and "element_cache" in artifacts:
        return {**artifacts["element_cache"], "store_stats": element_stats()}
    return {"route": route, "note": "element cache not applicable to clone route"}


def _design_rules_for_report(design_dna: dict | None) -> dict:
    if not design_dna:
        return {"has_rules": False, "findings": [], "finding_count": 0}
    try:
        from ..design_rules import build_design_rules, validate_design
        rules = build_design_rules(design_dna)
        findings = validate_design(design_dna, rules)
        return {"has_rules": True, "findings": findings, "finding_count": len(findings)}
    except Exception:
        return {"has_rules": False, "findings": [], "finding_count": 0}


def _component_matches_for_report(document) -> dict:
    try:
        stored = list_components()
        library = {"components": stored} if stored else {"components": []}
        return match_components(library, document)
    except Exception:
        return {"schema": "component-match/v1", "components": [], "matches": [], "unmatched": []}


# ---- main pipeline ------------------------------------------------------

def run_pipeline(
    markdown: str,
    *,
    out_dir: str | Path,
    density: str = "standard",
    engine: str = "solver",
    llm_fn: Callable[[str], str] | None = None,
    agent: PptAgent | None = None,
    gate_deck: bool = True,
    template_path: str | Path | None = None,
    template_dna: dict[str, Any] | None = None,
    design_dna: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Markdown -> delivered deck + the full decision report.

    Route is auto-resolved: template provided -> clone, absent -> designed.
    """
    agent = agent or PptAgent()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # route resolution (fix: not hardcoded to "designed")
    has_template = template_path is not None and Path(template_path).exists()
    mode_report = resolve_fidelity_mode(
        None if has_template else "designed",
        template_dna=template_dna if has_template else None,
    )
    route = mode_report.get("mode") or "designed"
    fingerprint = ""
    if design_dna:
        fingerprint = check_template_consistency(design_dna, template_dna or {})

    # 1-2. parse + analyze
    document = parse_markdown(markdown, source="pipeline")
    analyzed = analyze_content(document)

    # 3. narrative (the only stage that may touch a model)
    narrative = build_narrative(analyzed, llm_fn=llm_fn)

    # 4. plan + archetypes
    plan = build_presentation_plan(analyzed, density=density)
    annotated = annotate_plan(plan, analyzed)

    artifacts: dict[str, Any] = {}
    pages_dropped = 0
    repair_report: dict[str, Any] = {}
    audit_report: dict[str, Any] = {}

    if route == "clone" and template_path:
        # ---- clone route: template chrome inherited verbatim ----
        from ..clone_build import render_clone_deck, plan_template

        # capacity check: limit pages to what the template can serve
        template_plan = plan_template(template_path)
        shells = template_plan.get("shells") or {}
        max_content = (shells.get("content") or 0) + (shells.get("toc") or 0)
        max_section = shells.get("section") or 0
        max_cover = shells.get("cover") or 0
        max_closing = shells.get("closing") or shells.get("close") or shells.get("cover") or 0
        
        original_total = len(annotated.get("pages") or [])
        content_used = 0
        section_used = 0
        limited_pages = []
        for pg in annotated.get("pages") or []:
            kind = pg.get("kind")
            if kind == "content":
                if content_used >= max_content:
                    continue
                content_used += 1
            elif kind == "section":
                if section_used >= max_section:
                    continue
                section_used += 1
            elif kind == "cover":
                if max_cover < 1:
                    continue
            elif kind == "closing":
                if max_closing < 1:
                    continue
            limited_pages.append(pg)
        annotated["pages"] = limited_pages
        annotated["page_total"] = len(limited_pages)
        pages_dropped = original_total - len(limited_pages)
        
        pptx_path = out / "deck.pptx"
        clone_pages = _plan_to_clone_pages(annotated, document)
        clone_result = render_clone_deck(
            template_path, clone_pages, pptx_path,
            audit=True, fidelity=True,
        )
        artifacts["pptx"] = str(pptx_path)
        artifacts["clone_audit"] = clone_result.get("audit") or {}
        audit_report = clone_result.get("audit") or {}
        repair_report = {
            "stop_reason": "clone (template geometry preserved)",
            "residual_count": 0,
        }
    else:
        # ---- designed route: theme-driven from scratch ----
        from ..agent.plan_to_ir import plan_to_ir
        from ..repair import run_repair_cycle

        presentation, element_cache = plan_to_ir(
            annotated, analyzed, title=document.title,
            llm_fn=llm_fn, template_fingerprint=fingerprint,
            layout_engine=engine,
        )
        boxes = [
            {"x": c.x or 0, "y": c.y or 0, "w": c.w or 1, "h": c.h or 1,
             "absolute": True, "text": c.text or ""}
            for slide in presentation.slides for c in slide.components
        ]
        repair_report = run_repair_cycle(boxes, 13.333, 7.5)
        pptx_path = out / "deck.pptx"
        render_result = agent.render(presentation, pptx_path).to_dict()
        html_path = out / "deck.html"
        agent.render(presentation, html_path, renderer="html").to_dict()
        artifacts["pptx"] = str(pptx_path)
        artifacts["html"] = str(html_path)
        artifacts["element_cache"] = element_cache

    # QA gate: page audit on the output deck
    gate_report = {"passed": None, "mode": "skipped"}
    if gate_deck and artifacts.get("pptx") and Path(artifacts["pptx"]).exists():
        try:
            gate_report = agent.gate(Path(artifacts["pptx"]), workspace=out / "qa")
        except Exception as exc:
            gate_report = {"passed": False, "mode": "error", "error": str(exc)}

    # clone audit (chrome inheritance check)
    if route == "clone" and artifacts.get("pptx"):
        try:
            from ..clone_build import audit_deck
            audit_report = audit_deck(Path(artifacts["pptx"]))
            artifacts["clone_audit"] = audit_report
        except Exception as exc:
            audit_report = {"error": str(exc)}
            artifacts["clone_audit"] = audit_report

    has_rasterizer = _detect_rasterizer()

    return {
        "schema": SCHEMA,
        "title": annotated.get("title") or document.title or "Presentation",
        "page_total": len(annotated.get("pages") or []),
        "route": route,
        "route_basis": mode_report.get("basis"),
        "template_fingerprint": fingerprint or None,
        "pages_dropped": pages_dropped,
        "stages": {
            "parse": {"format": document.format, "blocks": len(document.blocks)},
            "analyze": {"analyzer": analyzed.metadata.get("analyzer")},
            "narrative": {"mode": narrative["mode"], "arc": narrative["arc"]},
            "plan": {"page_total": plan["page_total"]},
            "archetypes": {
                page["page_no"]: (page.get("archetype") or {}).get("archetype")
                for page in annotated["pages"] if page["kind"] == "content"
            },
            "fidelity": {"mode": route, "basis": mode_report.get("basis")},
            "repair": repair_report,
        },
        "artifacts": artifacts,
        "clone_audit": audit_report,
        "gates": {
            "fidelity_report": gates_report(
                route, has_design_rules=bool(design_dna), has_rasterizer=has_rasterizer
            ),
            "delivery": gate_report,
        },
        "element_cache": _element_cache_for_report(route, artifacts),
        "design_rules": _design_rules_for_report(design_dna),
        "component_matches": _component_matches_for_report(analyzed),
        "metadata": {"llm": narrative["metadata"]["llm"], "pipeline": f"{route}+rules"},
    }
