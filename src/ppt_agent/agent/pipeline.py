"""The V2.2 end-to-end pipeline: every layer, one honest report.

Route resolution is automatic:
* ``template_dna`` provided -> **clone route** (template chrome inherited verbatim)
* ``template_dna`` absent   -> **designed route** (theme-driven from scratch)

The clone route converts the presentation plan into clone page specs and
calls ``clone_build.render_clone_deck`` -- the SAME code path the MCP tools
use. The output inherits every untouched decoration byte-identically.

Intelligent condensation: the agent designs the page count (target <= 25).
When content exceeds capacity the plan merges low-priority sections and
caps content pages. The report states what was condensed and why.
"""

from __future__ import annotations

import copy as _copy
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

SCHEMA = "pipeline/v2"
MAX_TOTAL_PAGES = 25


def _detect_rasterizer() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


# ---- report helpers -------------------------------------------------------

def _element_cache_for_report(route: str, artifacts: dict) -> dict:
    if route == "designed" and "element_cache" in artifacts:
        from ..element_store import stats as element_stats
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
        from ..component_matcher import match_components
        from ..component_store import list_components
        stored = list_components()
        library = {"components": stored} if stored else {"components": []}
        return match_components(library, document)
    except Exception:
        return {"schema": "component-match/v1", "components": [], "matches": [], "unmatched": []}


# ---- intelligent condensation ---------------------------------------------

def condense_plan(
    plan: dict[str, Any],
    document: Any,
    *,
    max_total: int = MAX_TOTAL_PAGES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Limit the plan to <= ``max_total`` pages WITHOUT losing the narrative.

    Red line: every chapter's section spine is preserved. The old strategy
    deleted whole low-priority chapters, which turned a four-part report into a
    one-chapter deck with an empty TOC. Instead we now:

    1. keep cover / toc / closing and *all* section pages;
    2. hand out the remaining content budget to chapters in proportion to how
       many content pages they generated, guaranteeing each chapter at least
       one content page where possible;
    3. within a chapter, drop the lowest-value content pages first (hard
       numbers and tables are worth most).
    """
    condensed = _copy.deepcopy(plan)
    pages = condensed.get("pages") or []
    original_total = len(pages)

    fixed = [p for p in pages if p.get("kind") in ("cover", "toc", "closing")]
    sections = [p for p in pages if p.get("kind") == "section"]
    contents = [p for p in pages if p.get("kind") == "content"]

    section_budget = len(fixed) + len(sections)
    content_budget = max(0, max_total - section_budget)

    if len(contents) <= content_budget:
        return condensed, {"original": original_total, "final": len(pages),
                           "max_total": max_total, "sections_merged": 0,
                           "pages_dropped": 0, "strategy": "within budget"}

    block_lookup = {b.id: b for b in document.blocks}

    def content_value(pg: dict[str, Any]) -> float:
        blocks = [block_lookup.get(bid) for bid in pg.get("source_blocks") or []]
        metrics = sum(1 for b in blocks if b and b.text and any(c.isdigit() for c in b.text))
        tables = sum(1 for b in blocks if b and b.type == "table")
        return metrics + tables * 3 + len(pg.get("source_blocks") or [])

    def section_of(pg: dict[str, Any]) -> str:
        return pg.get("title") or ""

    by_section: dict[str, list[dict[str, Any]]] = {}
    for pg in contents:
        by_section.setdefault(section_of(pg), []).append(pg)

    # proportional quota per chapter, then rebalance leftover capacity
    n_sections = max(1, len(by_section))
    remaining = content_budget
    quota: dict[str, int] = {}
    order = sorted(by_section, key=lambda t: len(by_section[t]), reverse=True)
    for i, title in enumerate(order):
        available_sections = len(order) - i
        pool = by_section[title]
        # fair share of what is left, but never starve later chapters
        share = max(1, round(remaining / available_sections))
        take = min(share, len(pool), remaining)
        quota[title] = take
        remaining -= take

    keep_ids: set[int] = set()
    dropped_pages = 0
    for title, pool in by_section.items():
        allowance = quota.get(title, 0)
        ranked = sorted(pool, key=content_value, reverse=True)
        keep = ranked[:allowance]
        dropped_pages += len(pool) - len(keep)
        keep_ids.update(id(p) for p in keep)

    new_pages = [p for p in pages if p.get("kind") != "content" or id(p) in keep_ids]
    new_pages.sort(key=lambda p: p.get("page_no") or 0)
    condensed["pages"] = new_pages
    condensed["page_total"] = len(new_pages)

    return condensed, {
        "original": original_total, "final": len(new_pages), "max_total": max_total,
        "sections_merged": 0, "pages_dropped": dropped_pages,
        "spine_sections": len(sections),
        "strategy": "kept every chapter spine; trimmed lowest-value content pages",
    }


# ---- clone page spec builder ----------------------------------------------

_KIT_ROTATION: dict[str, list[str]] = {
    "cards_grid": ["quad_cards", "column_cards", "stage_cards"],
    "metrics_row": ["quad_cards", "stage_cards", "column_cards"],
    "timeline": ["progress_timeline", "stage_timeline"],
    "comparison": ["two_panel_list", "column_cards"],
    "table_page": ["column_cards", "stage_cards"],
    "narrative": ["column_cards", "stage_cards"],
    "quote_strip": ["column_cards"],
    "title_bullets": ["quad_cards", "column_cards", "stage_cards"],
}


def _archetype_to_kit(archetype: str, item_count: int, rotation: int = 0) -> str:
    from ..clone_build import KITS
    candidates = _KIT_ROTATION.get(archetype, ["column_cards"])
    kit = candidates[rotation % len(candidates)]
    # item-count guards
    if kit == "quad_cards" and item_count > 6:
        kit = "column_cards"
    elif kit == "two_panel_list" and item_count < 2:
        kit = "column_cards"
    elif kit == "org_chart" and item_count < 3:
        kit = "quad_cards"
    return kit if kit in KITS else "column_cards"


def _blocks_to_quad_cards(blocks: list, *, page_title: str = "") -> list[dict[str, Any]]:
    """Format for quad_cards: {"title", "body", "icon"}"""
    cards = []
    icons = ["⚙", "📊", "🔬", "🎯"]
    pt = page_title.strip()
    for i, block in enumerate(blocks):
        if block.type in ("bullets", "ordered") and block.items:
            for j, item in enumerate(block.items[:4]):
                parts = item.split("：", 1) if "：" in item else item.split(":", 1)
                if len(parts) > 1:
                    title = parts[0].strip()[:15]
                    body = parts[1].strip()
                elif len(item) > 20:
                    title = item[:15]
                    body = item[15:]
                else:
                    title = item
                    body = ""
                cards.append({"title": title, "body": body, "icon": icons[j % 4]})
        elif block.text:
            if pt and block.text.strip() == pt:
                continue
            parts = block.text.split("：", 1) if "：" in block.text else block.text.split(":", 1)
            title = parts[0].strip()[:15] if len(parts) > 1 else block.text[:15]
            body = parts[1].strip() if len(parts) > 1 else block.text
            cards.append({"title": title, "body": body, "icon": icons[i % 4]})
    return cards[:4]


def _blocks_to_column_cards(blocks: list, *, page_title: str = "") -> list[dict[str, Any]]:
    """Format for column_cards: {"title", "sub", "lines": [...], "grad": bool}"""
    cards = []
    pt = page_title.strip()
    for block in blocks:
        if block.type in ("bullets", "ordered") and block.items:
            for item in block.items:
                if pt and item.strip() == pt:
                    continue
                parts = item.split("：", 1) if "：" in item else item.split(":", 1)
                if len(parts) == 2:
                    cards.append({"title": parts[0].strip()[:12], "lines": [parts[1].strip()], "grad": True})
                else:
                    cards.append({"title": "", "lines": [item], "grad": True})
        elif block.type == "table":
            for row in block.rows:
                title = row[0] if row else ""
                lines = [c for c in row[1:] if c]
                cards.append({"title": title[:12], "lines": lines, "grad": True})
        elif block.text:
            if pt and block.text.strip() == pt:
                continue
            parts = block.text.split("：", 1) if "：" in block.text else block.text.split(":", 1)
            if len(parts) == 2:
                cards.append({"title": parts[0].strip()[:12], "lines": [parts[1].strip()], "grad": True})
            else:
                cards.append({"title": block.text[:12], "lines": [block.text], "grad": True})
    return cards


def _blocks_to_steps(blocks: list) -> list[dict[str, Any]]:
    """Format for progress_timeline: {"date","status","title","desc"}"""
    steps = []
    for block in blocks:
        items = block.items if block.type in ("bullets", "ordered") else [block.text or ""]
        for j, item in enumerate(items):
            parts = item.split("：", 1) if "：" in item else item.split(":", 1)
            title = parts[0].strip()[:15] if len(parts) > 1 else item[:15]
            desc = parts[1].strip() if len(parts) > 1 else item
            steps.append({"date": f"Step {j+1}", "status": "done", "title": title, "desc": desc})
    return steps


def _blocks_to_two_panel(blocks: list) -> tuple[dict, dict]:
    """Format for two_panel_list: {title, rows: [[head, desc], ...]}"""
    left = {"title": "现状", "rows": []}
    right = {"title": "方案", "rows": []}
    target = left
    for block in blocks:
        text = block.text or ""
        items = block.items if block.type in ("bullets", "ordered") else [text]
        for item in items:
            if "vs" in item.lower() or "对比" in item or "相较" in item or "方案" in item:
                target = right
                continue
            parts = item.split("：", 1) if "：" in item else item.split(":", 1)
            head = parts[0].strip()[:10] if len(parts) > 1 else item[:10]
            desc = parts[1].strip() if len(parts) > 1 else item
            target["rows"].append([head, desc])
    return left, right


def _blocks_to_stages(blocks: list, *, page_title: str = "") -> list[dict[str, str]]:
    """Format for stage_cards: {"head", "desc"}"""
    stages: list[dict[str, str]] = []
    pt = (page_title or "").strip()
    for block in blocks:
        if block.type in ("bullets", "ordered") and block.items:
            for item in block.items:
                if pt and item.strip() == pt:
                    continue
                parts = item.split("：", 1) if "：" in item else item.split(":", 1)
                head = parts[0].strip()[:10] if len(parts) > 1 else item[:10]
                desc = parts[1].strip() if len(parts) > 1 else item
                stages.append({"head": head, "desc": desc})
        elif block.text:
            if pt and block.text.strip() == pt:
                continue
            stages.append({"head": block.text[:10], "desc": block.text})
    return stages


_DATE_RE = __import__("re").compile(
    r"(20\d{2})[\s年./-]{0,2}(\d{1,2})?[\s月./-]{0,2}(\d{1,2})?[日号]?"
)


def _derive_cover_meta(document) -> str:
    """Best-effort date string pulled from the document body.

    Returns "" when nothing date-shaped is found. Never fabricates a
    date; the caller draws nothing in that case, which is correct.
    """
    for block in document.blocks[:20]:
        text = block.text or " ".join(block.items or [])
        m = _DATE_RE.search(text)
        if m and m.group(1) and 1900 < int(m.group(1)) < 2100:
            year = m.group(1)
            month = m.group(2)
            day = m.group(3)
            parts = [year + "年"]
            if month:
                parts.append(month + "月")
            if day:
                parts.append(day + "日")
            return " ".join(parts)
    return ""


def _coerce_design_plan(plan):
    """Accept either a raw page list or a ``{deck, meta, pages}`` envelope."""
    if isinstance(plan, list):
        return plan
    if isinstance(plan, dict):
        pages = plan.get("pages")
        if isinstance(pages, list):
            return pages
    raise ValueError("design_plan must be a list of page specs or a dict with a pages list")


def _plan_to_clone_pages(
    plan: dict[str, Any],
    document: Any,
) -> list[dict[str, Any]]:
    """Convert a presentation plan into clone-route page specs (correct formats)."""
    lookup = {block.id: block for block in document.blocks}
    section_titles = [
        str(page.get("title") or "")
        for page in plan.get("pages") or []
        if page.get("kind") == "section"
    ]

    doc_title = document.title or "Presentation"
    pages: list[dict[str, Any]] = []
    _content_rotation = 0
    _section_count = 1

    for page in plan.get("pages") or []:
        kind = str(page.get("kind") or "content")
        archetype = (page.get("archetype") or {}).get("archetype") or "title_bullets"
        blocks = [lookup[bid] for bid in page.get("source_blocks") or [] if bid in lookup]

        if kind == "cover":
            pages.append({
                "role": "cover",
                "pill": page.get("pill") or "",
                "title": page.get("title") or doc_title,
                "meta": page.get("meta") or _derive_cover_meta(document),
            })
        elif kind == "toc":
            items = []
            for sec_page in (plan.get("pages") or []):
                if sec_page.get("kind") != "section":
                    continue
                st = str(sec_page.get("title") or "")
                sub_blocks = [lookup.get(bid) for bid in (sec_page.get("source_blocks") or []) if bid in lookup]
                subs = []
                for b in sub_blocks:
                    if b.type in ("bullets", "ordered") and b.items:
                        subs.extend(b.items[:4])
                    elif b.text:
                        subs.append(b.text)
                sub_text = " · ".join(subs[:4]) if subs else ""
                if sub_text == st:
                    sub_text = ""
                items.append({"title": st, "sub": sub_text})
            pages.append({
                "role": "toc",
                "title": "目录",
                "title_en": "CONTENTS",
                "items": items,
            })
        elif kind == "section":
            section_children = [
                lookup[bid] for bid in page.get("source_blocks") or [] if bid in lookup
            ]
            lines = []
            for b in section_children:
                if b.type in ("bullets", "ordered"):
                    lines.extend(b.items[:3])
                elif b.text:
                    lines.append(b.text)
            pages.append({
                "role": "section",
                "title": page.get("title") or "",
                "lines": lines[:3],
                "chapter_num": f"{_section_count:02d}",
            })
            _section_count += 1
        elif kind == "closing":
            pages.append({
                "role": "closing",
                "title": "谢谢",
                "sub": "请各位领导批评指正",
                "meta": doc_title,
            })
        else:
            kit = _archetype_to_kit(archetype, len(blocks), rotation=_content_rotation)
            _content_rotation += 1
            page_title = page.get("title") or ""
            # filter out blocks whose text matches the page title (avoids
            # card titles duplicating the page header)
            lead_blocks = [lookup[bid] for bid in page.get("source_blocks") or [] if bid in lookup]
            lead_text = ""
            for lb in lead_blocks:
                if lb.type in ("heading", "paragraph") and lb.text and not lead_text:
                    lead_text = lb.text[:40]
                    break
            if lead_text == page_title:
                lead_text = ""
            spec: dict[str, Any] = {
                "role": "content",
                "kit": kit,
                "title": page_title,
                "lead": lead_text or None,
            }
            if kit == "quad_cards":
                spec["cards"] = _blocks_to_quad_cards(blocks, page_title=page_title)
            elif kit == "progress_timeline":
                spec["steps"] = _blocks_to_steps(blocks)
            elif kit == "two_panel_list":
                left, right = _blocks_to_two_panel(blocks)
                spec["left"] = left
                spec["right"] = right
            elif kit == "stage_cards":
                spec["stages"] = _blocks_to_stages(blocks, page_title=page_title)
            else:
                spec["cards"] = _blocks_to_column_cards(blocks, page_title=page_title)
            pages.append(spec)

    return pages


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
    design_plan: list[dict[str, Any]] | dict[str, Any] | None = None,
    assets_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Markdown -> delivered deck + the full decision report."""
    agent = agent or PptAgent()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    has_template = template_path is not None and Path(template_path).exists()
    if has_template and not template_dna:
        # A template was supplied but no DNA was pre-extracted: derive it here
        # so the clone route engages instead of silently falling to the
        # designed path. This is the single source of the template identity.
        from ..template import analyze_pptx
        template_dna = analyze_pptx(Path(template_path))
    if has_template and not design_dna:
        from ..design_dna import build_design_dna
        design_dna = build_design_dna(template_dna)
    mode_report = resolve_fidelity_mode(
        None if has_template else "designed",
        template_dna=template_dna if has_template else None,
    )
    route = mode_report.get("mode") or "designed"
    fingerprint = ""
    if design_dna:
        fingerprint = check_template_consistency(design_dna, template_dna or {})

    document = parse_markdown(markdown, source="pipeline")
    analyzed = analyze_content(document)
    narrative = build_narrative(analyzed, llm_fn=llm_fn)
    plan = build_presentation_plan(analyzed, density=density)

    condensation_report = {
        "original": len(plan.get("pages") or []),
        "final": len(plan.get("pages") or []),
        "strategy": "no condensation needed", "pages_dropped": 0,
    }

    # Page budget is driven by the content, not by how many template slides
    # exist: the clone route renders every page on Blank layouts with DNA-
    # inherited chrome, so it can author any number of pages. The old
    # "2 + template shells" cap belonged to the verbatim shell-reuse route
    # and wrongly collapsed decks to ~11 pages; MAX_TOTAL_PAGES (<=25) is the
    # only real ceiling, per the design brief.
    max_total = MAX_TOTAL_PAGES
    if design_plan:
        # An externally designed plan is authoritative -- do not condense it.
        max_total = max(max_total, len(design_plan if isinstance(design_plan, list) else design_plan.get("pages") or []))

    if len(plan.get("pages") or []) > max_total:
        plan, condensation_report = condense_plan(plan, document, max_total=max_total)
        condensation_report["template_capacity"] = max_total

    annotated = annotate_plan(plan, analyzed)

    artifacts: dict[str, Any] = {}
    repair_report: dict[str, Any] = {}
    audit_report: dict[str, Any] = {}
    fallback_reason: str | None = None

    design_plan_source = "auto"
    rendered_pages: int | None = None
    if route == "clone" and template_path:
        from ..blank_deck import render_blank_deck
        pptx_path = out / "deck.pptx"
        if design_plan:
            clone_pages = _coerce_design_plan(design_plan)
            design_plan_source = "external"
        else:
            clone_pages = _plan_to_clone_pages(annotated, document)
        try:
            clone_result = render_blank_deck(clone_pages, pptx_path, design_dna=design_dna,
                                      assets_dir=assets_dir)
            artifacts["pptx"] = str(pptx_path)
            rendered_pages = int(clone_result.get("pages") or len(clone_pages))
            artifacts["clone_audit"] = {"warnings": clone_result.get("warnings", [])}
            audit_report = {"warnings": clone_result.get("warnings", [])}
            repair_report = {"stop_reason": "clone (blank layout)", "residual_count": 0}
        except Exception as clone_exc:
            route = "designed"
            fallback_reason = str(clone_exc)
            repair_report = {"stop_reason": f"clone fallback: {clone_exc}", "residual_count": -1, "fallback_reason": str(clone_exc)}

    if route == "designed":
        from ..agent.plan_to_ir import plan_to_ir
        from ..repair import run_repair_cycle
        presentation, element_cache = plan_to_ir(
            annotated, analyzed, title=document.title,
            llm_fn=llm_fn, template_fingerprint=fingerprint, layout_engine=engine,
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

    gate_report = {"passed": None, "mode": "skipped"}
    if gate_deck and artifacts.get("pptx") and Path(artifacts["pptx"]).exists():
        try:
            gate_report = agent.gate(Path(artifacts["pptx"]), workspace=out / "qa")
        except Exception as exc:
            gate_report = {"passed": False, "mode": "error", "error": str(exc)}

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
        "page_total": rendered_pages if rendered_pages is not None else len(annotated.get("pages") or []),
        "route": route,
        "route_basis": mode_report.get("basis"),
        "fallback_reason": fallback_reason,
        "template_fingerprint": fingerprint or None,
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
        "design_plan": {"source": design_plan_source},
        "artifacts": artifacts,
        "clone_audit": audit_report,
        "element_cache": _element_cache_for_report(route, artifacts),
        "design_rules": _design_rules_for_report(design_dna),
        "component_matches": _component_matches_for_report(analyzed),
        "gates": {
            "fidelity_report": gates_report(
                route, has_design_rules=bool(design_dna), has_rasterizer=has_rasterizer
            ),
            "delivery": gate_report,
        },
        "metadata": {"llm": narrative["metadata"]["llm"], "pipeline": f"{route}+rules"},
    }




