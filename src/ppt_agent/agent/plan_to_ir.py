"""Plan -> Universal Presentation IR with solver-computed absolute geometry.

V2.2: the designed route now consumes per-page-kind DNA so cover pages look
like the template's cover, content pages like the template's content pages,
and so on. Elements are resolved through the persistent element store
(cache hit = zero generation cost); on a miss they are generated (rules
first, LLM as bounded fallback) and stored for reuse.

Clone route (template DNA given) still refuses honestly -- it belongs in the
clone tools. The ``page_kind_dna`` and ``element_cache_report`` parameters
are new in V2.2 and optional (defaults keep V2.1 behaviour).
"""

from __future__ import annotations

import copy
from typing import Any, Callable

from ..component_store import find_by_kind, increment_usage
from ..component_style import apply_dna_to_slots
from ..content_ir import ContentDocument
from ..contracts import IR_SCHEMA_VERSION, check_template_dna_version
from ..element_generator import generate_with_cache
from ..page_kind_dna import get_kind_dna
from ..ir import Component, Presentation, Slide
from ..styling import resolve_layout

SLIDE_SIZE_IN = (13.333, 7.5)

_PURPOSE_BY_KIND = {
    "cover": "cover",
    "toc": "agenda",
    "section": "section",
    "content": "content",
    "closing": "closing",
}

_DEFAULT_PRIMARY = "0A3A52"  # only when NO kind_dna and NO theme available


def _component_text(block: Any) -> str | None:
    if block.type in ("bullets", "ordered"):
        marker = "-" if block.type == "bullets" else None
        lines = [f"- {item}" if marker else item for item in block.items]
        return "\n".join(lines) if lines else None
    if block.type == "table":
        return None
    return block.text or None


def _resolve_background(kind: str, kind_dna: dict[str, Any]) -> dict[str, Any]:
    """Background fill for one page kind, from its DNA segment or a fallback."""
    color = (kind_dna.get("color") or {})
    surface = color.get("surface")
    primary = color.get("primary")
    if kind in ("cover", "section", "closing"):
        rgb = primary or _DEFAULT_PRIMARY
        return {"fill": {"type": "solid", "rgb": rgb}}
    rgb = surface or "FFFFFF"
    return {"fill": {"type": "solid", "rgb": rgb}}


def _resolve_text_color(kind: str, kind_dna: dict[str, Any]) -> str:
    color = (kind_dna.get("color") or {})
    if kind in ("cover", "section", "closing"):
        return color.get("surface") or "FFFFFF"
    return color.get("text") or "262626"


def _element_spec_for_block(block: Any, archetype: str) -> dict[str, Any]:
    """Map a content block + archetype to an element store lookup spec."""
    spec: dict[str, Any] = {"type": "body", "text": block.text or ""}
    if block.type in ("bullets", "ordered"):
        spec = {"type": "bullet_list", "items": block.items}
    elif block.type == "table":
        spec = {"type": "table", "headers": block.headers, "rows": block.rows}
    elif block.type == "quote":
        spec = {"type": "quote", "text": block.text}
    if archetype == "cards_grid" and block.type in ("bullets", "ordered"):
        spec["type"] = "card"
    elif archetype == "metrics_row" and block.type in ("bullets", "ordered"):
        spec["type"] = "metric"
    return spec


def plan_to_ir(
    plan: dict[str, Any],
    document: ContentDocument,
    *,
    title: str | None = None,
    template_dna: dict[str, Any] | None = None,
    page_kind_dna: dict[str, Any] | None = None,
    llm_fn: Callable[[str], str] | None = None,
    template_fingerprint: str = "",
    layout_engine: str = "solver",
) -> tuple[Presentation, dict[str, Any]]:
    """Annotated Presentation Plan -> (Presentation IR, element cache report).

    Returns a tuple so the pipeline can surface the element cache report
    (hits / misses / tokens saved) without parsing the IR to recover it.
    """
    if template_dna is not None:
        check_template_dna_version(template_dna)
        raise ValueError(
            "plan_to_ir implements the DESIGNED route; template DNA implies the "
            "clone route -- use ppt_agent_clone_plan/clone_build/clone_audit"
        )

    lookup = {block.id: block for block in document.blocks}
    slides: list[Slide] = []
    width_in, height_in = SLIDE_SIZE_IN

    section_titles = [
        str(page.get("title") or "")
        for page in plan.get("pages") or []
        if page.get("kind") == "section"
    ]

    cache_report: dict[str, Any] = {"hits": 0, "misses": 0, "llm_calls": 0, "tokens_estimate": 0}

    for page in plan.get("pages") or []:
        kind = str(page.get("kind") or "content")
        purpose = _PURPOSE_BY_KIND.get(kind, "content")
        archetype = (page.get("archetype") or {}).get("archetype") or "title_bullets"

        kind_dna = get_kind_dna(page_kind_dna, kind) if page_kind_dna else {}
        components: list[Component] = []
        slide_data: dict[str, Any] = {}

        if kind_dna:
            slide_data["background"] = _resolve_background(kind, kind_dna)
        elif kind in ("cover", "section", "closing"):
            slide_data["background"] = {"fill": {"type": "solid", "rgb": _DEFAULT_PRIMARY}}

        text_color = _resolve_text_color(kind, kind_dna) if kind_dna else None

        if page.get("title"):
            style: dict[str, Any] = {}
            if text_color:
                style["font"] = {"color": text_color}
            components.append(Component(type="title", text=str(page["title"]), style=style))

        if kind == "toc" and section_titles:
            components.append(Component(
                type="body",
                text="\n".join(f"- {name}" for name in section_titles),
            ))

        # try stored components first (zero generation cost)
        stored = find_by_kind(archetype, item_count=len(page.get("source_blocks") or []))
        if stored:
            component_template = stored[0]
            styled_slots = apply_dna_to_slots(component_template, page_kind_dna or {}, kind) if page_kind_dna else component_template.get("slots") or []
            for slot in styled_slots:
                cache_report["hits"] += 1
                increment_usage(component_template.get("component_id") or "")
                components.append(Component(
                    type=slot.get("role") or "body",
                    text=slot.get("text"),
                    style=slot.get("style") or {},
                ))
        else:
            for block_id in page.get("source_blocks") or []:
                block = lookup.get(block_id)
                if block is None:
                    continue
                spec = _element_spec_for_block(block, archetype)
                element, meta = generate_with_cache(
                    spec, llm_fn=llm_fn, template_fingerprint=template_fingerprint
                )
                cache_report["hits" if meta.get("cache") == "hit" else "misses"] += 1
                cache_report["tokens_estimate"] += meta.get("tokens_estimate") or 0
                if meta.get("generator") == "llm":
                    cache_report["llm_calls"] += 1

                style = dict(element.get("_style") or {})
                if text_color and not style.get("font"):
                    style["font"] = {"color": text_color}

                if block.type == "table":
                    components.append(Component(
                        type="table",
                        text="\n".join(block.headers) if block.headers else None,
                        style=style,
                        data={"headers": block.headers, "rows": block.rows},
                    ))
                else:
                    components.append(Component(
                        type=element.get("type") or "body",
                        text=element.get("text") or _component_text(block),
                        style=style,
                    ))

        slide = Slide(
            id=f"slide-{page.get('page_no', len(slides) + 1):02d}",
            purpose=purpose, components=components, data=slide_data or None,
        )
        resolved = resolve_layout(slide, width_in, height_in, engine=layout_engine)
        for component, box in zip(slide.components, resolved):
            component.x, component.y = round(box.x, 4), round(box.y, 4)
            component.w, component.h = round(box.w, 4), round(box.h, 4)
        slides.append(slide)

    presentation = Presentation(
        version=IR_SCHEMA_VERSION,
        title=title or document.title or "Presentation",
        slides=slides,
    )
    cache_report["hit_rate"] = (
        cache_report["hits"] / (cache_report["hits"] + cache_report["misses"])
        if (cache_report["hits"] + cache_report["misses"]) else 0.0
    )
    return presentation, cache_report
