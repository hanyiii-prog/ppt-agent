"""The V3 rebuild pipeline: understand, plan, resolve a visual system, build.

The V3 pipeline is deliberately additive to the existing V2 route.  It starts
from source provenance and an explicit page plan, then compiles pages from a
small set of self-owned design systems.  It does not let a model invent facts
or paint unvalidated geometry: the model may choose titles, messages and page
grouping, while this module validates them and owns the final layout.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .content_analyzer import analyze_content
from .content_ir import ContentBlock, ContentDocument
from .ir import Component, Presentation, Provenance, Slide
from .parsers import parse_auto
from .presentation_plan import build_presentation_plan
from .storyboard import build_storyboard


SOURCE_PACK_SCHEMA = "source-pack/v1"
EVIDENCE_GRAPH_SCHEMA = "evidence-graph/v1"
DECK_BRIEF_SCHEMA = "deck-brief/v1"
OUTLINE_SCHEMA = "outline/v1"
SLIDE_SPEC_SCHEMA = "slide-spec/v1"
TEMPLATE_PROFILE_SCHEMA = "template-profile/v1"
PAGE_DESIGN_IR_SCHEMA = "page-design-ir/v1"
REPORT_SCHEMA = "ppt-agent-v3-report/v1"


@dataclass
class SourceRef:
    id: str
    path: str
    format: str
    priority: str
    content_hash: str
    block_ids: list[str] = field(default_factory=list)


@dataclass
class SourcePack:
    schema: str
    title: str | None
    sources: list[SourceRef]
    blocks: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_document(cls, document: ContentDocument, source_path: Path) -> "SourcePack":
        raw = source_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        ref = SourceRef(
            id="source-001",
            path=str(source_path),
            format=str(document.format or source_path.suffix.lstrip(".")),
            priority="primary",
            content_hash=digest,
            block_ids=[block.id for block in document.blocks],
        )
        return cls(
            schema=SOURCE_PACK_SCHEMA,
            title=document.title,
            sources=[ref],
            blocks=[_block_to_dict(block) for block in document.blocks],
            metadata={"parser": document.metadata, "warnings": []},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceGraph:
    schema: str
    facts: list[dict[str, Any]]
    relations: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_source_pack(cls, pack: SourcePack) -> "EvidenceGraph":
        # The rule path records each original block as a claim.  Semantic
        # merging can refine these later, but it must never lose the original
        # text or provenance.
        facts: list[dict[str, Any]] = []
        for index, block in enumerate(pack.blocks, 1):
            text = _block_payload_text(block)
            facts.append({
                "id": f"fact-{index:04d}",
                "claim": text,
                "source_block_ids": [block["id"]],
                "fact_type": block.get("type") or "narrative",
                "confidence": 1.0,
                "locked": True,
            })
        return cls(schema=EVIDENCE_GRAPH_SCHEMA, facts=facts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeckBrief:
    schema: str
    audience: dict[str, Any]
    objective: str
    context: str
    tone: list[str]
    page_budget: dict[str, int]
    must_include: list[str]
    must_not_invent: bool
    template_preference: str | None
    visual_constraints: list[str]

    @classmethod
    def from_task(cls, task: dict[str, Any], max_pages: int = 25) -> "DeckBrief":
        if not isinstance(task, dict):
            raise ValueError("task constraints must be an object")
        page_budget = task.get("page_budget") if isinstance(task.get("page_budget"), dict) else {}
        maximum = _positive_int(page_budget.get("max"), _positive_int(task.get("max_pages"), max_pages))
        minimum = _positive_int(page_budget.get("min"), 1)
        if minimum > maximum:
            raise ValueError("page_budget.min cannot exceed page_budget.max")
        return cls(
            schema=DECK_BRIEF_SCHEMA,
            audience={
                "name": str(task.get("audience") or "general audience"),
                "knowledge_level": str(task.get("knowledge_level") or "mixed"),
                "decision_power": str(task.get("decision_power") or "medium"),
            },
            objective=str(task.get("objective") or task.get("task") or "present the supplied material clearly"),
            context=str(task.get("context") or ""),
            tone=_string_list(task.get("tone")) or ["formal", "credible"],
            page_budget={"min": minimum, "max": maximum},
            must_include=_string_list(task.get("must_include")),
            must_not_invent=True,
            template_preference=_optional_text(task.get("template")),
            visual_constraints=_string_list(task.get("visual_constraints")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Outline:
    schema: str
    title: str
    slides: list[dict[str, Any]]
    omissions: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    planning_mode: str = "rules"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


BUILTIN_TEMPLATES: dict[str, dict[str, Any]] = {
    "executive-briefing": {
        "id": "executive-briefing",
        "display_name": "Executive Briefing",
        "scenarios": ["report", "decision", "progress", "review"],
        "tones": ["formal", "credible", "concise"],
        "theme": {
            "colors": {
                "primary": "17324B", "primary_deep": "0E2233",
                "accent": "C6602D", "surface": "F4F6F8", "panel": "DDE5EC",
                "text": "1F2937", "muted": "5D6D78", "inverse": "FFFFFF",
                "line": "B7C2CC",
            },
            "fonts": {"title": "Segoe UI", "body": "Segoe UI"},
            "type_scale": {"cover_title": 44, "title": 30, "takeaway": 20, "body": 18, "meta": 12},
        },
    },
    "data-analysis": {
        "id": "data-analysis",
        "display_name": "Data Analysis",
        "scenarios": ["analysis", "comparison", "data", "review"],
        "tones": ["formal", "analytical", "credible"],
        "theme": {
            "colors": {
                "primary": "23505B", "primary_deep": "133840",
                "accent": "B48A3C", "surface": "F5F7F7", "panel": "DFE9E8",
                "text": "212B30", "muted": "5D6B6E", "inverse": "FFFFFF",
                "line": "AEC0BF",
            },
            "fonts": {"title": "Segoe UI", "body": "Segoe UI"},
            "type_scale": {"cover_title": 42, "title": 28, "takeaway": 20, "body": 17, "meta": 12},
        },
    },
    "project-progress": {
        "id": "project-progress",
        "display_name": "Project Progress",
        "scenarios": ["progress", "project", "plan", "report"],
        "tones": ["formal", "practical", "credible"],
        "theme": {
            "colors": {
                "primary": "2E4F4F", "primary_deep": "1D3636",
                "accent": "C4762C", "surface": "F5F6F5", "panel": "E0E8E5",
                "text": "202B28", "muted": "5C6A66", "inverse": "FFFFFF",
                "line": "B4C4BF",
            },
            "fonts": {"title": "Segoe UI", "body": "Segoe UI"},
            "type_scale": {"cover_title": 43, "title": 29, "takeaway": 20, "body": 18, "meta": 12},
        },
    },
    "minimal-editorial": {
        "id": "minimal-editorial",
        "display_name": "Minimal Editorial",
        "scenarios": ["narrative", "proposal", "brief", "education"],
        "tones": ["clear", "modern", "quiet"],
        "theme": {
            "colors": {
                "primary": "303446", "primary_deep": "22252F",
                "accent": "7C6F53", "surface": "F7F7F7", "panel": "E8E6E2",
                "text": "272727", "muted": "636363", "inverse": "FFFFFF",
                "line": "C4C1BB",
            },
            "fonts": {"title": "Segoe UI", "body": "Segoe UI"},
            "type_scale": {"cover_title": 46, "title": 30, "takeaway": 19, "body": 17, "meta": 12},
        },
    },
}


def build_source_pack(path: str | Path) -> tuple[ContentDocument, SourcePack]:
    source_path = Path(path)
    if not source_path.is_file():
        raise FileNotFoundError(f"source file does not exist: {source_path}")
    document = parse_auto(source_path)
    return document, SourcePack.from_document(document, source_path)


def build_evidence_graph(document: ContentDocument, pack: SourcePack) -> EvidenceGraph:
    return EvidenceGraph.from_source_pack(pack)


def select_template(brief: DeckBrief) -> dict[str, Any]:
    preference = brief.template_preference
    if preference:
        if preference in BUILTIN_TEMPLATES:
            profile = BUILTIN_TEMPLATES[preference]
            return {
                **profile,
                "schema": TEMPLATE_PROFILE_SCHEMA,
                "source_kind": "builtin",
                "selection": {"score": 1.0, "reasons": ["selected by user"], "fallbacks": []},
            }
        profile = BUILTIN_TEMPLATES["executive-briefing"]
        return {
            **profile,
            "schema": TEMPLATE_PROFILE_SCHEMA,
            "source_kind": "builtin",
            "selection": {
                "score": 0.0,
                "reasons": [f"unknown template preference {preference!r}; fallback used"],
                "fallbacks": [],
            },
        }

    objective = brief.objective.lower()
    text = " ".join([brief.objective, brief.context] + brief.tone).lower()
    scores: dict[str, tuple[float, list[str]]] = {}
    for template_id, profile in BUILTIN_TEMPLATES.items():
        score = 0.0
        reasons: list[str] = []
        for token in profile["scenarios"]:
            if token in text:
                score += 0.22
                reasons.append(f"objective matches {token}")
        for tone in brief.tone:
            if tone.lower() in {item.lower() for item in profile["tones"]}:
                score += 0.16
                reasons.append(f"tone matches {tone}")
        if any(token in objective for token in ("数据", "analysis", "compare", "comparison")):
            if "data" in profile["scenarios"]:
                score += 0.2
        if any(token in objective for token in ("项目", "progress", "进展", "计划")):
            if "progress" in profile["scenarios"]:
                score += 0.2
        scores[template_id] = (min(1.0, score), reasons or ["balanced generic fit"])
    ranked = sorted(scores.items(), key=lambda item: (-item[1][0], item[0]))
    winner, (score, reasons) = ranked[0]
    profile = BUILTIN_TEMPLATES[winner]
    return {
        **profile,
        "schema": TEMPLATE_PROFILE_SCHEMA,
        "source_kind": "builtin",
        "selection": {
            "score": round(score, 3),
            "reasons": reasons,
            "fallbacks": [item[0] for item in ranked[1:3]],
        },
    }


def _rule_outline(document: ContentDocument, pack: SourcePack, brief: DeckBrief) -> Outline:
    slides: list[dict[str, Any]] = [{
        "id": "slide-0001", "kind": "cover", "title": document.title or pack.title or "Presentation",
        "purpose": "establish topic and context", "takeaway": "",
        "source_block_ids": [], "evidence_ids": [], "visual_form": "cover", "relations": [],
        "speaker_notes": "", "archetype": None, "layout_variant": "standard",
    }]
    index = 0
    blocks = document.blocks
    while index < len(blocks):
        block = blocks[index]
        group: list[ContentBlock] = []
        title = document.title or "Content"
        if block.type == "heading" and (block.level or 1) <= 2:
            title = block.text or title
            group = [block]
            index += 1
            while index < len(blocks):
                nxt = blocks[index]
                if nxt.type == "heading" and (nxt.level or 1) <= 2:
                    break
                group.append(nxt)
                index += 1
        else:
            # Group a few non-heading blocks to avoid one paragraph per page.
            while index < len(blocks):
                nxt = blocks[index]
                if nxt.type == "heading" and (nxt.level or 1) <= 2:
                    break
                group.append(nxt)
                index += 1
                if sum(_block_volume(item) for item in group) > 500:
                    break
        refs = [item.id for item in group]
        takeaway = _short_takeaway(group)
        slides.append({
            "id": f"slide-{len(slides) + 1:04d}", "kind": "content",
            "title": title, "purpose": f"explain {title}", "takeaway": takeaway,
            "source_block_ids": refs, "evidence_ids": refs,
            "visual_form": _rule_visual_form(group), "relations": _rule_relations(group),
            "speaker_notes": "", "archetype": None, "layout_variant": "standard",
        })
    slides.append({
        "id": f"slide-{len(slides) + 1:04d}", "kind": "closing", "title": "Thank you",
        "purpose": "close the presentation", "takeaway": "", "source_block_ids": [],
        "evidence_ids": [], "visual_form": "closing", "relations": [],
        "speaker_notes": "", "archetype": None, "layout_variant": "standard",
    })
    return Outline(
        schema=OUTLINE_SCHEMA, title=document.title or pack.title or "Presentation",
        slides=slides, planning_mode="rules",
    )


def _model_outline(
    document: ContentDocument, analyzed: ContentDocument, brief: DeckBrief,
    llm_fn: Callable[[str], str],
) -> tuple[Outline, dict[str, Any]]:
    result = build_storyboard(
        analyzed, llm_fn=llm_fn,
        constraints={
            "objective": brief.objective, "audience": brief.audience,
            "tone": brief.tone, "max_pages": brief.page_budget["max"],
            "visual_constraints": brief.visual_constraints,
        },
    )
    storyboard = result.get("storyboard")
    if not isinstance(storyboard, dict):
        return _rule_outline(document, SourcePack.from_document(analyzed, Path(document.source or "input")), result), {
            "mode": "rules_fallback", "error": result.get("error"),
        }
    raw_slides = list(storyboard.get("slides") or [])
    if raw_slides and raw_slides[0].get("kind") != "cover":
        raw_slides.insert(0, {
            "kind": "cover", "title": document.title or "Presentation",
            "key_message": "", "source_blocks": [], "visual_form": "cover",
            "speaker_notes": "", "archetype_name": None, "layout_variant": "standard",
        })
    if not raw_slides or raw_slides[-1].get("kind") != "closing":
        if not raw_slides or len(raw_slides) < brief.page_budget["max"]:
            raw_slides.append({
                "kind": "closing", "title": "Thank you",
                "key_message": "", "source_blocks": [], "visual_form": "closing",
                "speaker_notes": "", "archetype_name": None, "layout_variant": "standard",
            })
    slides: list[dict[str, Any]] = []
    for number, item in enumerate(raw_slides, 1):
        refs = list(item.get("source_blocks") or item.get("source_block_ids") or [])
        slides.append({
            "id": f"slide-{number:04d}", "kind": item.get("kind") or "content",
            "title": item.get("title") or f"Slide {number}",
            "purpose": item.get("key_message") or item.get("visual_form") or "present evidence",
            "takeaway": item.get("key_message") or "",
            "source_block_ids": refs, "evidence_ids": refs,
            "visual_form": item.get("visual_form") or "", "relations": [],
            "speaker_notes": item.get("speaker_notes") or "",
            "archetype": item.get("archetype_name"), "layout_variant": item.get("layout_variant"),
        })
    return Outline(
        schema=OUTLINE_SCHEMA, title=document.title or "Presentation",
        slides=slides, omissions=list(storyboard.get("omitted_source_blocks") or []),
        warnings=list(storyboard.get("warnings") or []), planning_mode="model",
    ), {"mode": "model", "error": None}


def build_page_design_ir(outline: Outline, template: dict[str, Any], document: ContentDocument) -> dict[str, Any]:
    lookup = {block.id: block for block in document.blocks}
    pages: list[dict[str, Any]] = []
    for number, item in enumerate(outline.slides, 1):
        blocks = [lookup[ref] for ref in item.get("source_block_ids") or [] if ref in lookup]
        pages.append({
            "page_no": number, "page_id": item["id"], "slide_spec_id": item["id"],
            "kind": item["kind"], "title": item["title"], "takeaway": item.get("takeaway") or "",
            "purpose": item.get("purpose") or "", "visual_form": item.get("visual_form") or "",
            "relations": item.get("relations") or [], "blocks": [_block_to_dict(block) for block in blocks],
            "template_family": "cover" if item["kind"] == "cover" else "closing" if item["kind"] == "closing" else "content",
            "composition": item.get("visual_form") or "text_evidence",
            "speaker_notes": item.get("speaker_notes") or "", "warnings": [],
        })
    return {
        "schema": PAGE_DESIGN_IR_SCHEMA,
        "template_id": template["id"],
        "theme": template["theme"],
        "pages": pages,
    }


def compile_presentation(design_ir: dict[str, Any], evidence: EvidenceGraph) -> Presentation:
    theme = design_ir.get("theme") or {}
    colors = theme.get("colors") or {}
    fonts = theme.get("fonts") or {}
    scale = theme.get("type_scale") or {}
    slides: list[Slide] = []
    for page in design_ir.get("pages") or []:
        slides.append(_compile_slide(page, colors, fonts, scale, evidence))
    return Presentation(
        version="0.1",
        title=str(design_ir.get("title") or "Presentation"),
        slides=slides,
        theme={"slide_size_inches": {"width": 13.333, "height": 7.5}, **theme},
    )


def _compile_slide(
    page: dict[str, Any], colors: dict[str, str], fonts: dict[str, str], scale: dict[str, Any],
    evidence: EvidenceGraph,
) -> Slide:
    kind = str(page.get("kind") or "content")
    primary = colors.get("primary", "1F2937")
    deep = colors.get("primary_deep", primary)
    accent = colors.get("accent", "C6602D")
    surface = colors.get("surface", "FFFFFF")
    panel = colors.get("panel", "EEEEEE")
    text_color = colors.get("text", "1F2937")
    muted = colors.get("muted", "555555")
    inverse = colors.get("inverse", "FFFFFF")
    line = colors.get("line", "CCCCCC")
    title_font = fonts.get("title", "Segoe UI")
    body_font = fonts.get("body", "Segoe UI")
    title_size = _number(scale.get("title"), 30)
    body_size = _number(scale.get("body"), 18)
    cover_title_size = _number(scale.get("cover_title"), 44)
    meta_size = _number(scale.get("meta"), 12)
    components: list[Component] = []

    def text(comp_type: str, value: str, x: float, y: float, w: float, h: float, *, size: float,
             rgb: str, bold: bool = False, align: str = "left") -> Component:
        return Component(
            type=comp_type, id=f"{page['page_id']}-{comp_type}-{len(components) + 1:02d}",
            x=x, y=y, w=w, h=h, text=value,
            style={"font": {"name": title_font if comp_type in {"title", "heading", "subtitle"} else body_font,
                            "size_pt": size, "rgb": rgb, "bold": bold, "alignment": align}},
        )

    def rect(value_id: str, x: float, y: float, w: float, h: float, rgb: str, opacity: float = 1.0) -> Component:
        return Component(
            type="shape", id=f"{page['page_id']}-{value_id}", x=x, y=y, w=w, h=h,
            style={"fill": {"rgb": rgb, "opacity": opacity}},
        )

    provenance = _provenance(page, evidence)
    title = str(page.get("title") or "")
    if kind == "cover":
        components.extend([
            rect("background", 0.0, 0.0, 13.333, 7.5, deep),
            rect("accent", 0.0, 4.9, 13.333, 0.09, accent),
            text("subtitle", str(page.get("purpose") or ""), 1.1, 2.0, 8.5, 0.5,
                 size=_number(scale.get("takeaway"), 20) + 1, rgb=accent),
            text("title", title, 1.1, 2.55, 10.2, 2.0, size=cover_title_size, rgb=inverse, bold=True),
        ])
    elif kind == "closing":
        components.extend([
            rect("background", 0.0, 0.0, 13.333, 7.5, deep),
            rect("accent", 5.97, 3.05, 1.4, 0.09, accent),
            text("title", title or "Thank you", 1.0, 3.35, 11.3, 1.2, size=40, rgb=inverse,
                 bold=True, align="center"),
            text("meta", str(page.get("takeaway") or ""), 1.0, 4.65, 11.3, 0.6, size=meta_size + 2,
                 rgb=inverse, align="center"),
        ])
    else:
        components.extend([
            text("title", title, 0.8, 0.55, 10.0, 0.85, size=title_size, rgb=deep, bold=True),
            rect("accent", 0.8, 1.38, 0.9, 0.075, accent),
        ])
        takeaway = str(page.get("takeaway") or "")
        if takeaway:
            components.append(text("takeaway", takeaway, 0.8, 1.62, 11.7, 0.55,
                                   size=_number(scale.get("takeaway"), 20), rgb=primary, bold=True))
        body_top = 2.4
        blocks = page.get("blocks") or []
        table_block = next((block for block in blocks if block.get("type") == "table"), None)
        if table_block:
            rows = [table_block.get("headers") or []]
            rows.extend(table_block.get("rows") or [])
            rows = rows[:7]
            components.append(Component(
                type="table", id=f"{page['page_id']}-table-01", x=0.8, y=body_top, w=11.7, h=2.4,
                data={"rows": rows}, provenance=provenance,
            ))
        else:
            body_text = _page_body_text(blocks)
            if body_text:
                components.append(Component(
                    type="body", id=f"{page['page_id']}-body-01", x=0.8, y=body_top, w=11.7, h=4.2,
                    text=body_text,
                    style={"font": {"name": body_font, "size_pt": body_size, "rgb": text_color}},
                    provenance=provenance,
                ))
        visual = str(page.get("visual_form") or "")
        if any(name in visual.lower() for name in ("progress", "timeline", "flow", "sequence")):
            components.append(rect("sequence-rule", 0.8, 6.7, 11.7, 0.03, line))
            for index in range(4):
                x = 1.4 + index * 2.9
                components.extend([
                    Component(type="shape", id=f"{page['page_id']}-dot-{index + 1:02d}", x=x, y=6.61,
                              w=0.2, h=0.2, style={"fill": {"rgb": accent}, "shape": "ellipse"}),
                    text("label", f"Stage {index + 1}", x + 0.3, 6.82, 1.5, 0.35, size=meta_size, rgb=muted),
                ])
        elif any(name in visual.lower() for name in ("comparison", "contrast")):
            components.extend([
                rect("left-panel", 0.8, 6.1, 5.75, 0.9, panel),
                rect("right-panel", 6.75, 6.1, 5.75, 0.9, panel),
                text("left-label", "Current state", 1.05, 6.32, 5.2, 0.45, size=meta_size + 2, rgb=text_color),
                text("right-label", "Target state", 7.0, 6.32, 5.2, 0.45, size=meta_size + 2, rgb=text_color),
            ])
    if not components:
        raise ValueError(f"page {page.get('page_id')} compiled to no components")
    return Slide(
        id=str(page["page_id"]), purpose=kind, claim=title,
        layout=str(page.get("composition") or kind), components=components,
        speaker_notes=str(page.get("speaker_notes") or ""),
        data={"background": {"fill": {"rgb": surface}}} if kind != "cover" and kind != "closing" else {},
    )


def evaluate_deck(
    presentation: Presentation, outline: Outline, pack: SourcePack, evidence: EvidenceGraph,
    artifacts: dict[str, Any], planning_mode: str = "rules",
) -> dict[str, Any]:
    facts = evidence.facts if isinstance(evidence, EvidenceGraph) else evidence.get("facts") or []
    outline_slides = outline.slides if isinstance(outline, Outline) else outline.get("slides") or []
    outline_omissions = (
        outline.omissions if isinstance(outline, Outline)
        else outline.get("omissions") or []
    )
    used = {
        ref
        for slide in outline_slides
        for ref in (slide.get("source_block_ids") or [])
    } | {item["id"] for item in outline_omissions}
    source_ids = {block["id"] for block in pack.blocks}
    missing = sorted(source_ids - used)
    unknown = sorted(used - source_ids)
    content_pages = [slide for slide in outline_slides if slide.get("kind") == "content"]
    missing_takeaways = [
        slide.get("id") for slide in content_pages
        if not str(slide.get("takeaway") or "").strip()
    ]
    evidence_ids = {fact["id"] for fact in facts}
    block_to_fact = {block["id"]: f"fact-{index:04d}" for index, block in enumerate(pack.blocks, 1)}
    referenced_facts = [
        block_to_fact[ref]
        for slide in outline_slides
        for ref in slide.get("source_block_ids") or []
        if ref in block_to_fact
    ]
    report = {
        "schema": "quality-report/v3",
        "status": "passed" if not missing and not unknown and not missing_takeaways else "failed",
        "content_quality": {
            "source_coverage": round((len(source_ids) - len(missing)) / max(1, len(source_ids)), 3),
            "missing_source_blocks": missing,
            "unknown_source_blocks": unknown,
            "missing_takeaways": missing_takeaways,
            "evidence_traceability": round(len(set(referenced_facts)) / max(1, len(evidence_ids)), 3),
        },
        "structural_quality": {
            "page_total": len(presentation.slides),
                "outline_page_total": len(outline_slides),
                "slides_match_outline": len(presentation.slides) == len(outline_slides),
            "empty_slides": [slide.id for slide in presentation.slides if not slide.components],
            "empty_titles": [slide.id for slide in presentation.slides if not str(slide.claim or "").strip()],
        },
        "visual_quality": {
            "model_review": "not_run",
            "warning": "No vision model was passed to this V3 run; semantic visual review was not executed.",
        },
        "planning_mode": planning_mode,
    }
    return report


def build_v3_deck(
    source: str | Path,
    output: str | Path,
    *,
    llm_fn: Callable[[str], str] | None = None,
    task: dict[str, Any] | None = None,
    template_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compatibility facade for the modular V3 pipeline."""
    from .pipeline import run_v3_pipeline

    modular_report = run_v3_pipeline(
        source,
        output,
        task=task,
        llm_fn=llm_fn,
        template_path=template_path,
    )
    planning_report = {
        "mode": modular_report.get("planning", {}).get("mode", "rules"),
        "error": None,
        "outline_review": modular_report.get("planning", {}).get("outline_review"),
    }
    workspace = Path(output)
    outline_data = json.loads((workspace / "outline.json").read_text(encoding="utf-8"))
    template_profile = json.loads((workspace / "template-profile.json").read_text(encoding="utf-8"))
    quality = {
        "content_quality": modular_report.get("content_quality", {}),
        "structural_quality": modular_report.get("structural_quality", {}),
        "visual_quality": modular_report.get("visual_quality", {}),
        "render": modular_report.get("render", {}),
        "status": modular_report.get("status", "failed"),
    }
    if quality["visual_quality"].get("model_review") != "used":
        quality["visual_quality"]["model_review"] = "not_run"
    return {
        "schema": REPORT_SCHEMA,
        "status": modular_report["status"],
        "title": outline_data.get("title", "Presentation"),
        "page_total": modular_report.get("page_total", 0),
        "brief": json.loads((Path(output) / "deck-brief.json").read_text(encoding="utf-8")),
        "planning": planning_report,
        "template": {
            "id": modular_report.get("template", {}).get("id"),
            "source": template_profile.get("source_kind"),
            "selection": template_profile.get("selection"),
        },
        "quality": quality,
        "artifacts": modular_report.get("artifacts", {}),
    }


def _validate_outline(outline: Outline, pack: SourcePack, brief: DeckBrief) -> None:
    source_ids = {block["id"] for block in pack.blocks}
    used = {
        ref
        for slide in outline.slides
        for ref in (slide.get("source_block_ids") or [])
    } | {item["id"] for item in outline.omissions}
    unknown = sorted(used - source_ids)
    if unknown:
        raise ValueError(f"outline references unknown source blocks: {unknown}")
    max_pages = brief.page_budget["max"]
    if len(outline.slides) > max_pages:
        raise ValueError(f"outline has {len(outline.slides)} pages, exceeding max {max_pages}")
    for slide in outline.slides:
        if not slide.get("purpose"):
            raise ValueError(f"outline slide {slide.get('id')} has no purpose")
        if slide.get("kind") == "content" and not str(slide.get("takeaway") or "").strip():
            raise ValueError(f"outline content slide {slide.get('id')} has no takeaway")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _block_to_dict(block: ContentBlock) -> dict[str, Any]:
    value: dict[str, Any] = {"id": block.id, "type": block.type}
    if block.text is not None:
        value["text"] = block.text
    if block.level is not None:
        value["level"] = block.level
    if block.items:
        value["items"] = block.items
    if block.headers:
        value["headers"] = block.headers
    if block.rows:
        value["rows"] = block.rows
    if block.source:
        value["source"] = block.source
    return value


def _block_payload_text(block: dict[str, Any]) -> str:
    if block.get("type") == "table":
        rows = [block.get("headers") or []] + [row for row in (block.get("rows") or [])]
        return " | ".join(" / ".join(str(cell) for cell in row) for row in rows if row)
    if block.get("items"):
        return "; ".join(str(item) for item in block["items"])
    return str(block.get("text") or "")


def _block_volume(block: ContentBlock) -> int:
    if block.type == "table":
        return len(block.headers) + sum(len(row) for row in block.rows) * 12
    if block.type in {"bullets", "ordered"}:
        return sum(len(item) for item in block.items)
    return len(block.text or "")


def _page_body_text(blocks: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for block in blocks:
        if block.get("type") == "heading":
            continue
        payload = _block_payload_text(block)
        if payload:
            prefix = "" if block.get("type") == "paragraph" else "• "
            lines.append(prefix + payload)
    return "\n".join(lines)


def _short_takeaway(blocks: list[ContentBlock]) -> str:
    non_headings = [block for block in blocks if block.type != "heading"]
    if any(block.type in {"bullets", "ordered"} for block in blocks):
        return "Supporting points are summarised below"
    if any(block.type == "table" for block in blocks):
        return "Key items and current status are summarised below"
    for block in blocks:
        if block in non_headings and block.type in {"bullets", "ordered"}:
            text = _block_payload_text(_block_to_dict(block))
            return text[:110] + ("..." if len(text) > 110 else "")
    for block in non_headings:
        text = _block_payload_text(_block_to_dict(block))
        if text:
            return text[:110] + ("..." if len(text) > 110 else "")
    return "No supporting content"


def _rule_visual_form(blocks: list[ContentBlock]) -> str:
    if any(block.type == "table" for block in blocks):
        return "table_evidence"
    if any(block.type in {"bullets", "ordered"} and any(ch.isdigit() for ch in item) for block in blocks for item in block.items):
        return "progress_sequence"
    return "text_evidence"


def _rule_relations(blocks: list[ContentBlock]) -> list[str]:
    form = _rule_visual_form(blocks)
    if form == "progress_sequence":
        return ["sequence", "progress"]
    if form == "table_evidence":
        return ["comparison", "distribution"]
    return ["part_of"]


def _provenance(page: dict[str, Any], evidence: EvidenceGraph) -> list[Provenance]:
    result: list[Provenance] = []
    for block in page.get("blocks") or []:
        result.append(Provenance(source_id=str(block.get("source") or "source"), locator=block.get("id"), quote=_block_payload_text(block)))
    return result


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value > 0:
        return value
    return default


def _number(value: Any, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return default
    return float(value)


__all__ = [
    "BUILTIN_TEMPLATES",
    "DeckBrief",
    "EvidenceGraph",
    "Outline",
    "SourcePack",
    "build_evidence_graph",
    "build_page_design_ir",
    "build_source_pack",
    "build_v3_deck",
    "compile_presentation",
    "evaluate_deck",
    "select_template",
]
