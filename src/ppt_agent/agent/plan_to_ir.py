"""Plan -> Universal Presentation IR with solver-computed absolute geometry.

The Presentation Plan (kind + archetype + source blocks) becomes IR slides
whose components carry **explicit geometry**: the layout solver (batch 3.D)
resolves the flow once here, and the renderers then place everything
verbatim through the absolute-geometry path -- the invariant-safe route.

Kind mapping: cover -> cover, toc -> agenda, section -> section,
content -> content, closing -> closing. Content pages become a title
component plus one body component per source block (tables keep their
structured data). Cloning stays on the clone tools: a template DNA payload
makes this module refuse honestly rather than imitate the clone route.
"""

from __future__ import annotations

from typing import Any

from ..content_ir import ContentDocument
from ..contracts import IR_SCHEMA_VERSION, check_template_dna_version
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


def _component_text(block: Any) -> str | None:
    if block.type in ("bullets", "ordered"):
        marker = "-" if block.type == "bullets" else None
        lines = [f"- {item}" if marker else item for item in block.items]
        return "\n".join(lines) if lines else None
    if block.type == "table":
        return None  # tables keep structured data below
    return block.text or None


def plan_to_ir(
    plan: dict[str, Any],
    document: ContentDocument,
    *,
    title: str | None = None,
    template_dna: dict[str, Any] | None = None,
) -> Presentation:
    """Annotated Presentation Plan -> Presentation IR (absolute geometry)."""
    if template_dna is not None:
        # refuse honestly: the clone route owns template-driven generation
        check_template_dna_version(template_dna)
        raise ValueError(
            "plan_to_ir implements the DESIGNED route; template DNA implies the "
            "clone route -- use ppt_agent_clone_plan/clone_build/clone_audit"
        )

    lookup = {block.id: block for block in document.blocks}
    slides: list[Slide] = []
    width_in, height_in = SLIDE_SIZE_IN
    # designed-route chrome, mirroring the design layer's treatment: dark
    # full-bleed surface for cover/section/closing, white for content pages
    DARK_BG = {"type": "solid", "rgb": "0A3A52"}
    DARK_TEXT = {"color": "FFFFFF"}

    section_titles = [
        str(page.get("title") or "")
        for page in plan.get("pages") or []
        if page.get("kind") == "section"
    ]

    for page in plan.get("pages") or []:
        kind = str(page.get("kind") or "content")
        purpose = _PURPOSE_BY_KIND.get(kind, "content")
        components: list[Component] = []
        slide_data: dict[str, Any] = {}

        if kind in ("cover", "section", "closing"):
            slide_data["background"] = {"fill": dict(DARK_BG)}
        if page.get("title"):
            style: dict[str, Any] = {"font": dict(DARK_TEXT)} if kind in ("cover", "section", "closing") else {}
            components.append(Component(type="title", text=str(page["title"]), style=style))
        if kind == "toc":
            # a TOC page shows the real agenda: the section titles
            if section_titles:
                components.append(Component(
                    type="body",
                    text="\n".join(f"- {name}" for name in section_titles),
                ))
        for block_id in page.get("source_blocks") or []:
            block = lookup.get(block_id)
            if block is None:
                continue
            text = _component_text(block)
            if block.type == "table":
                components.append(Component(
                    type="table",
                    text="；".join(block.headers) if block.headers else None,
                    data={"headers": block.headers, "rows": block.rows},
                ))
            elif text:
                components.append(Component(type="body", text=text))

        slide = Slide(id=f"slide-{page.get('page_no', len(slides) + 1):02d}",
                      purpose=purpose, components=components, data=slide_data or None)
        # the ONE layout algorithm resolves geometry; the solver stage upgrades
        # the flow while absolute decisions stay verbatim
        resolved = resolve_layout(slide, width_in, height_in, engine="solver")
        for component, box in zip(slide.components, resolved):
            component.x, component.y = round(box.x, 4), round(box.y, 4)
            component.w, component.h = round(box.w, 4), round(box.h, 4)
        slides.append(slide)

    return Presentation(
        version=IR_SCHEMA_VERSION,
        title=title or document.title or "Presentation",
        slides=slides,
    )
