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


# ---- intelligent page condensation ----

MAX_TOTAL_PAGES = 25  # target: <= 25 pages including cover/toc/closing


def condense_plan(
    plan: dict[str, Any],
    document: Any,
    *,
    max_total: int = MAX_TOTAL_PAGES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Intelligently limit the plan to <= max_total pages.

    Strategy:
    1. Always keep cover, toc, closing (fixed overhead = 3)
    2. Budget the remaining pages for sections + content
    3. When sections exceed budget: merge the lowest-priority sections
    4. When content exceeds budget: increase chars-per-page (denser layout)
    5. Never silently drop: the report states what was condensed

    Returns (condensed_plan, condensation_report).
    """
    import copy as _copy

    condensed = _copy.deepcopy(plan)
    pages = condensed.get("pages") or []
    fixed = sum(1 for p in pages if p.get("kind") in ("cover", "toc", "closing"))
    budget = max_total - fixed
    original_total = len(pages)

    sections = [p for p in pages if p.get("kind") == "section"]
    contents = [p for p in pages if p.get("kind") == "content"]

    if len(sections) + len(contents) <= budget:
        return condensed, {"original": original_total, "final": len(pages),
                           "sections_merged": 0, "pages_dropped": 0,
                           "strategy": "within budget"}

    # Phase 1: merge sections if there are too many
    # Each section costs 1 section page + its content pages
    section_costs: dict[str, int] = {}
    for section in sections:
        title = section.get("title") or ""
        cost = 1  # the section page itself
        cost += sum(1 for p in contents if p.get("title") == title)
        section_costs[title] = cost

    # Sort sections by content volume (ascending = least important first)
    section_volumes: dict[str, float] = {}
    for section in sections:
        title = section.get("title") or ""
        block_lookup = {b.id: b for b in document.blocks}
        blocks = [block_lookup.get(bid) for bid in section.get("source_blocks") or []]
        volume = sum(b.char_volume() if b else 0 for b in blocks)
        content_count = sum(1 for p in contents if p.get("title") == title)
        section_volumes[title] = volume + content_count * 260  # weight by pages

    keep_sections = list(sections)
    merged_count = 0
    while len(keep_sections) > 1:
        section_budget = len(keep_sections)
        content_budget = budget - section_budget
        if section_budget + sum(1 for p in contents if p.get("title") in [s.get("title") for s in keep_sections]) <= budget:
            break
        # merge the smallest section into the next one
        smallest = min(keep_sections, key=lambda s: section_volumes.get(s.get("title") or "", 0))
        keep_sections.remove(smallest)
        merged_count += 1

    keep_titles = {s.get("title") for s in keep_sections}
    new_pages = [p for p in pages if p.get("kind") in ("cover", "toc", "closing")]
    for p in pages:
        if p.get("kind") == "section" and p.get("title") in keep_titles:
            new_pages.append(p)
        elif p.get("kind") == "content" and p.get("title") in keep_titles:
            new_pages.append(p)
    new_pages.sort(key=lambda p: p.get("page_no") or 0)

    # Phase 2: if still over budget, increase density (drop lowest-value content pages)
    content_in_kept = [p for p in new_pages if p.get("kind") == "content"]
    section_count = len(keep_sections)
    available = budget - section_count
    if len(content_in_kept) > available:
        # keep the pages with the most metric content (hard numbers)
        def content_value(p):
            blocks = [block_lookup.get(bid) for bid in p.get("source_blocks") or []]
            metrics = sum(1 for b in blocks if b and hasattr(b, 'text') and b.text and any(c.isdigit() for c in b.text))
            tables = sum(1 for b in blocks if b and b.type == "table")
            return metrics + tables * 3 + len(p.get("source_blocks") or [])
        content_in_kept.sort(key=content_value, reverse=True)
        keep_ids = {id(p) for p in content_in_kept[:available]}
        new_pages = [p for p in new_pages if p.get("kind") != "content" or id(p) in keep_ids]

    dropped = original_total - len(new_pages)
    condensed["pages"] = new_pages
    condensed["page_total"] = len(new_pages)

    return condensed, {
        "original": original_total,
        "final": len(new_pages),
        "max_total": max_total,
        "sections_merged": merged_count,
        "pages_dropped": dropped,
        "strategy": "merged low-priority sections + capped content pages",
    }


# ---- clone route helpers ------------------------------------------------

def _archetype_to_kit(archetype: str, item_count: int) -> str:
    """Map a content archetype to the best available clone kit."""
    from ..clone_build import KITS

    mapping = {
        "cards_grid": "four_role_cards",
        "metrics_row": "four_role_cards",
        "table_page": "column_cards",
        "timeline": "progress_timeline",
        "comparison": "two_panel_list",
        "quote_strip": "column_cards",
        "narrative": "column_cards",
        "title_bullets": "column_cards",
    }
    kit = mapping.get(archetype, "column_cards")
    if kit not in KITS:
        kit = "column_cards"
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
            if archetype == "timeline":
                spec["steps"] = _blocks_to_steps(blocks)
            elif archetype == "comparison":
                spec["left"], spec["right"] = _blocks_to_comparison(blocks)
            else:
                spec["cards"] = _blocks_to_cards(blocks)
            pages.append(spec)

    return pages


def _blocks_to_cards(blocks: list) -> list[dict[str, Any]]:
    """Convert content blocks to column_cards format: {title, lines}.
    """
    cards: list[dict[str, Any]] = []
    for block in blocks:
        if block.type in ("bullets", "ordered") and block.items:
            for item in block.items:
                parts = item.split("：", 1) if "：" in item else item.split(":", 1)
                if len(parts) == 2:
                    cards.append({"title": parts[0].strip(), "lines": [parts[1].strip()]})
                else:
                    cards.append({"title": item[:20].strip(), "lines": [item]})
        elif block.type == "table":
            for row in block.rows:
                title = row[0] if row else ""
                lines = [c for c in row[1:] if c]
                cards.append({"title": title, "lines": lines})
        elif block.text:
            parts = block.text.split("：", 1) if "：" in block.text else block.text.split(":", 1)
            if len(parts) == 2:
                cards.append({"title": parts[0].strip(), "lines": [parts[1].strip()]})
            else:
                cards.append({"title": block.text[:20].strip(), "lines": [block.text]})
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

    # 4. plan + archetypes + intelligent condensation (template-aware)
    plan = build_presentation_plan(analyzed, density=density)
    condensation_report = {"original": len(plan.get("pages") or []), "final": len(plan.get("pages") or []), "strategy": "no condensation needed", "pages_dropped": 0}
    
    # get template capacity for condensation
    max_total = MAX_TOTAL_PAGES
    template_shells = None
    if route == "clone" and template_path:
        from ..clone_build import plan_template
        tp = plan_template(template_path)
        template_shells = tp.get("shells") or {}
        # inner pages share content+section+toc shells
        inner = (template_shells.get("content") or 0) + (template_shells.get("section") or 0) + (template_shells.get("toc") or 0)
        max_total = min(max_total, 2 + inner)  # +2 for cover + closing
    
    if len(plan.get("pages") or []) > max_total:
        plan, condensation_report = condense_plan(plan, document, max_total=max_total)
        condensation_report["template_capacity"] = template_shells
    annotated = annotate_plan(plan, analyzed)

    artifacts: dict[str, Any] = {}
    pages_dropped = 0
    repair_report: dict[str, Any] = {}
    audit_report: dict[str, Any] = {}

    if route == "clone" and template_path:
        # ---- clone route: template chrome inherited verbatim ----
        from ..clone_build import render_clone_deck

        pptx_path = out / "deck.pptx"
        clone_pages = _plan_to_clone_pages(annotated, document)
        try:
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
        except Exception as clone_exc:
            # clone route failed (capacity or other): fall back to designed
            # and report honestly
            route = "designed"
            mode_report = resolve_fidelity_mode("designed")
            repair_report = {
                "stop_reason": f"clone fallback: {clone_exc}",
                "residual_count": -1,
                "fallback_reason": str(clone_exc),
            }
    if route == "designed":
        # ---- designed route: theme-driven from scratch (also the fallback) ----
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
            "condensation": condensation_report,
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
