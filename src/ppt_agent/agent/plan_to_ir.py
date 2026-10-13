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
import math
import re
from typing import Any, Callable

from ..component_store import find_by_kind, increment_usage
from ..component_style import apply_dna_to_slots
from ..content_ir import ContentDocument
from ..contracts import IR_SCHEMA_VERSION, check_template_dna_version
from ..element_generator import generate_with_cache
from ..page_kind_dna import get_kind_dna
from ..ir import Component, Presentation, Provenance, Slide
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


def _hex_rgb(value: str) -> tuple[int, int, int]:
    value = str(value).strip().lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _luminance(value: str) -> float:
    channels = []
    for channel in _hex_rgb(value):
        normalized = channel / 255
        channels.append(normalized / 12.92 if normalized <= 0.04045 else ((normalized + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _readable_color(preferred: str, background: str) -> str:
    return preferred if _contrast(preferred, background) >= 4.5 else (
        "FFFFFF" if _contrast("FFFFFF", background) >= _contrast("111827", background) else "111827"
    )


def _story_palette(plan: dict[str, Any]) -> dict[str, str]:
    profile = plan.get("design_profile")
    palette = profile.get("palette") if isinstance(profile, dict) else None
    palette = palette if isinstance(palette, dict) else {}
    return {
        "primary": palette.get("primary", "0B4A42"),
        "accent": palette.get("accent", "D98942"),
        "surface": palette.get("surface", "F5F7F5"),
        "panel": palette.get("panel", "E8EFEC"),
        "text": palette.get("text", "1F2927"),
        "muted": palette.get("muted", "5D6D68"),
        "inverse": palette.get("inverse", "FFFFFF"),
    }


def _story_shape(
    x: float, y: float, w: float, h: float, fill: str, *, component_id: str
) -> Component:
    return Component(
        type="shape",
        id=component_id,
        x=x, y=y, w=w, h=h,
        style={"fill": {"type": "solid", "rgb": fill}, "line": {"type": "none"}},
    )


def _story_text(
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    size: float,
    color: str,
    background: str,
    bold: bool = False,
    alignment: str = "left",
    source_ids: list[str] | None = None,
    component_id: str | None = None,
) -> Component:
    text = str(text or "").strip()
    color = _readable_color(color, background)
    provenance = [Provenance(source_id=source_id) for source_id in (source_ids or [])]
    return Component(
        type="text",
        id=component_id,
        x=round(x, 3), y=round(y, 3), w=round(w, 3), h=round(h, 3),
        text=text,
        style={"font": {
            "size_pt": size, "rgb": color, "bold": bold, "alignment": alignment,
            "name": "Aptos",
        }},
        provenance=provenance,
    )


def _block_items(block: Any) -> list[str]:
    if block.type in ("bullets", "ordered"):
        return [str(item).strip() for item in block.items if str(item).strip()]
    if block.type == "table":
        rows = []
        for row in block.rows:
            parts = [
                f"{block.headers[index]}: {cell}" if index < len(block.headers) else str(cell)
                for index, cell in enumerate(row) if str(cell).strip()
            ]
            if parts:
                rows.append("  |  ".join(parts))
        return rows
    return [str(block.text).strip()] if block.text and block.text.strip() else []


def _story_items(page: dict[str, Any], blocks: list[Any]) -> list[tuple[str, Any]]:
    title = str(page.get("title") or "").strip().casefold()
    items: list[tuple[str, Any]] = []
    for block in blocks:
        if block.type == "heading" and (block.text or "").strip().casefold() == title:
            continue
        items.extend((text, block) for text in _block_items(block))
    return items


def _add_story_content(
    components: list[Component],
    page: dict[str, Any],
    items: list[tuple[str, Any]],
    palette: dict[str, str],
    *,
    y_top: float = 2.12,
) -> None:
    archetype = (page.get("archetype") or {}).get("archetype") or "title_bullets"
    variant = page.get("layout_variant") or "standard"
    accent = palette["accent"]
    text_color = palette["text"]
    if not items:
        return

    if archetype == "metrics_row":
        columns = min(4, len(items))
        gap = 0.22
        width = (11.65 - gap * (columns - 1)) / columns
        height = min(2.45, 4.15 / math.ceil(len(items) / columns) - 0.18)
        metric_re = re.compile(r"\d+(?:[,.]\d+)*(?:\.\d+)?%?")
        for index, (text, block) in enumerate(items):
            column = index % columns
            row = index // columns
            x = 0.84 + column * (width + gap)
            y = y_top + row * (height + 0.20)
            components.append(_story_shape(x, y, width, height, palette["panel"], component_id=f"metric-card-{index + 1}"))
            components.append(_story_shape(x, y, 0.07, height, accent, component_id=f"metric-accent-{index + 1}"))
            match = metric_re.search(text)
            value = match.group(0) if match else ""
            label = (text[:match.start()] + text[match.end():]).strip(" ：:，,") if match else text
            ids = [block.id]
            if value:
                components.append(_story_text(
                    value, x + 0.25, y + 0.27, width - 0.48, 0.62, size=25,
                    color=palette["primary"], background=palette["panel"], bold=True,
                    source_ids=ids, component_id=f"metric-value-{index + 1}",
                ))
            components.append(_story_text(
                label or text, x + 0.25, y + (0.98 if value else 0.30), width - 0.48,
                height - (1.12 if value else 0.48), size=15, color=text_color,
                background=palette["panel"], source_ids=ids,
                component_id=f"metric-label-{index + 1}",
            ))
        return

    if archetype == "timeline":
        count = len(items)
        slot_h = min(0.77, 4.45 / count)
        line_x = 1.12
        line_top = y_top + slot_h / 2
        components.append(_story_shape(line_x + 0.09, line_top, 0.035, max(0.05, slot_h * (count - 1)), palette["panel"], component_id="timeline-rule"))
        for index, (text, block) in enumerate(items):
            y = y_top + index * slot_h
            components.append(_story_shape(line_x, y + 0.16, 0.22, 0.22, accent, component_id=f"timeline-node-{index + 1}"))
            components.append(_story_text(
                text, 1.52, y + 0.04, 10.45, slot_h - 0.08, size=16,
                color=text_color, background=palette["surface"],
                source_ids=[block.id], component_id=f"timeline-text-{index + 1}",
            ))
        return

    if variant == "wide" and archetype not in {"timeline", "metrics_row", "quote_strip"}:
        slot_h = min(0.92, 4.35 / len(items))
        for index, (text, block) in enumerate(items):
            y = y_top + index * slot_h
            fill = palette["panel"] if index % 2 == 0 else "FFFFFF"
            components.append(_story_shape(0.84, y, 11.65, slot_h - 0.10, fill, component_id=f"wide-row-{index + 1}"))
            components.append(_story_shape(0.84, y, 0.07, slot_h - 0.10, accent, component_id=f"wide-accent-{index + 1}"))
            components.append(_story_text(
                text, 1.12, y + 0.08, 11.05, slot_h - 0.26,
                size=14 if variant == "compact" else 16, color=text_color,
                background=fill, source_ids=[block.id],
                component_id=f"wide-text-{index + 1}",
            ))
        return

    if archetype in {"cards_grid", "comparison"} or variant in {"split", "grid"}:
        columns = 3 if variant == "grid" else (2 if variant == "split" or archetype == "comparison" or len(items) <= 4 else 3)
        gap = 0.22
        width = (11.65 - gap * (columns - 1)) / columns
        rows = math.ceil(len(items) / columns)
        height = min(1.68, (4.45 - gap * (rows - 1)) / rows)
        for index, (text, block) in enumerate(items):
            x = 0.84 + (index % columns) * (width + gap)
            y = y_top + (index // columns) * (height + gap)
            fill = palette["panel"] if index % 2 == 0 else "FFFFFF"
            components.append(_story_shape(x, y, width, height, fill, component_id=f"content-card-{index + 1}"))
            components.append(_story_shape(x, y, 0.07, height, accent, component_id=f"content-accent-{index + 1}"))
            components.append(_story_text(
                text, x + 0.24, y + 0.16, width - 0.45, height - 0.30, size=15,
                color=text_color, background=fill, source_ids=[block.id],
                component_id=f"content-text-{index + 1}",
            ))
        return

    if archetype == "quote_strip":
        for index, (text, block) in enumerate(items[:3]):
            y = y_top + index * 1.42
            components.append(_story_shape(0.85, y, 0.08, 1.05, accent, component_id=f"quote-rule-{index + 1}"))
            components.append(_story_text(
                text, 1.15, y + 0.04, 10.8, 0.98, size=19, color=text_color,
                background=palette["surface"], source_ids=[block.id],
                component_id=f"quote-text-{index + 1}",
            ))
        return

    count = len(items)
    slot_h = min(0.62 if variant == "compact" else 0.82, 4.42 / count)
    for index, (text, block) in enumerate(items):
        y = y_top + index * slot_h
        components.append(_story_shape(0.91, y + 0.17, 0.11, 0.11, accent, component_id=f"bullet-{index + 1}"))
        components.append(_story_text(
            text, 1.25, y + 0.02, 10.85, slot_h - 0.05,
            size=14 if variant == "compact" else 16,
            color=text_color, background=palette["surface"],
            source_ids=[block.id], component_id=f"body-{index + 1}",
        ))


def _storyboard_presentation(
    plan: dict[str, Any],
    document: ContentDocument,
    *,
    title: str | None,
) -> tuple[Presentation, dict[str, Any]]:
    lookup = {block.id: block for block in document.blocks}
    palette = _story_palette(plan)
    profile = plan.get("design_profile") or {}
    typography = profile.get("typography") if isinstance(profile, dict) else {}
    typography = typography if isinstance(typography, dict) else {}
    title_font = str(typography.get("title_font") or "Aptos Display").strip()
    body_font = str(typography.get("body_font") or "Aptos").strip()
    pages = plan.get("pages") or []
    section_titles = [str(page.get("title") or "") for page in pages if page.get("kind") == "section"]
    slides: list[Slide] = []

    for index, page in enumerate(pages, start=1):
        kind = str(page.get("kind") or "content")
        purpose = _PURPOSE_BY_KIND.get(kind, "content")
        blocks = [lookup[block_id] for block_id in page.get("source_blocks") or [] if block_id in lookup]
        items = _story_items(page, blocks)
        page_title = str(page.get("title") or "")
        key_message = str(page.get("key_message") or "").strip()
        background = "FFFFFF"
        components: list[Component] = []
        source_ids = [block.id for block in blocks]

        if kind in ("cover", "closing"):
            background = palette["primary"]
            components.append(_story_shape(0.60, 0, 0.09, 7.5, palette["accent"], component_id="brand-spine"))
            components.append(_story_shape(1.10, 1.64, 1.10, 0.07, palette["accent"], component_id="title-rule"))
            components.append(_story_text(
                page_title, 1.10, 2.00, 10.9, 1.48, size=39 if kind == "cover" else 34,
                color=palette["inverse"], background=background, bold=True,
                source_ids=source_ids, component_id="page-title",
            ))
            subtitle = key_message or (items[0][0] if items else "")
            if subtitle and subtitle.casefold() != page_title.casefold():
                components.append(_story_text(
                    subtitle, 1.12, 3.72, 10.1, 0.88, size=19,
                    color=palette["inverse"], background=background,
                    source_ids=source_ids, component_id="key-message",
                ))
            if kind == "closing" and items:
                tail = [text for text, _block in items if text != subtitle]
                if tail:
                    components.append(_story_text(
                        tail[0], 1.12, 5.18, 10.1, 0.58, size=15,
                        color=palette["inverse"], background=background,
                        source_ids=source_ids, component_id="closing-detail",
                    ))
        elif kind == "toc":
            background = palette["surface"]
            components.append(_story_text(
                page_title, 0.84, 0.56, 11.65, 0.65, size=29,
                color=palette["text"], background=background, bold=True,
                component_id="page-title",
            ))
            for item_index, section_title in enumerate(section_titles):
                y = 1.64 + item_index * min(0.86, 4.85 / max(1, len(section_titles)))
                components.append(_story_shape(0.86, y, 11.6, 0.62, palette["panel"], component_id=f"toc-row-{item_index + 1}"))
                components.append(_story_text(
                    f"{item_index + 1:02d}", 1.08, y + 0.10, 0.82, 0.42, size=15,
                    color=palette["accent"], background=palette["panel"], bold=True,
                    component_id=f"toc-number-{item_index + 1}",
                ))
                components.append(_story_text(
                    section_title, 2.02, y + 0.09, 9.9, 0.44, size=17,
                    color=palette["text"], background=palette["panel"],
                    component_id=f"toc-title-{item_index + 1}",
                ))
        else:
            background = palette["surface"]
            components.append(_story_text(
                page_title, 0.84, 0.50, 11.65, 0.70, size=28,
                color=palette["text"], background=background, bold=True,
                source_ids=source_ids, component_id="page-title",
            ))
            components.append(_story_shape(0.84, 1.30, 0.92, 0.055, palette["accent"], component_id="header-rule"))
            content_top = 2.04
            if key_message and key_message.casefold() != page_title.casefold():
                callout_fill = palette["panel"]
                components.append(_story_shape(0.84, 1.52, 11.65, 0.42, callout_fill, component_id="message-panel"))
                components.append(_story_shape(0.84, 1.52, 0.07, 0.42, palette["accent"], component_id="message-accent"))
                components.append(_story_text(
                    key_message, 1.08, 1.56, 11.15, 0.32, size=14,
                    color=palette["text"], background=callout_fill,
                    source_ids=source_ids, component_id="key-message",
                ))
            if kind == "section" and not items:
                content_top = 2.58
                if key_message:
                    components.append(_story_text(
                        key_message, 0.92, 2.60, 10.8, 1.0, size=22,
                        color=palette["muted"], background=background,
                        source_ids=source_ids, component_id="section-summary",
                    ))
            else:
                if key_message and any(key_message.casefold() == text.casefold() for text, _block in items):
                    items = [(text, block) for text, block in items if text.casefold() != key_message.casefold()]
                _add_story_content(components, page, items, palette, y_top=content_top)

            components.append(_story_text(
                f"{index:02d} / {len(pages):02d}", 11.05, 6.93, 1.30, 0.28, size=9,
                color=palette["muted"], background=background, alignment="right",
                component_id="page-number",
            ))

        slide = Slide(
            id=f"slide-{index:02d}",
            purpose=purpose,
            claim=key_message or None,
            layout=page.get("layout_variant") or (page.get("archetype") or {}).get("archetype") or page.get("visual_form"),
            components=components,
            speaker_notes=page.get("speaker_notes"),
            data={
                "composition": "storyboard/v1",
                "background": {"fill": {"type": "solid", "rgb": background}},
                "visual_form": page.get("visual_form") or "",
                "evidence_ids": page.get("evidence_ids") or [],
            },
        )
        for component in components:
            if component.type != "text":
                continue
            font = component.style.setdefault("font", {})
            font["name"] = title_font if "title" in (component.id or "") else body_font
        slides.append(slide)

    task_spec = plan.get("task_spec")
    task_spec = task_spec if isinstance(task_spec, dict) else {}
    presentation = Presentation(
        version=IR_SCHEMA_VERSION,
        title=title or document.title or "Presentation",
        slides=slides,
        audience=str(task_spec.get("audience") or "") or None,
        objective=str(task_spec.get("objective") or "") or None,
    )
    return presentation, {
        "hits": 0, "misses": 0, "llm_calls": 0, "tokens_estimate": 0,
        "hit_rate": 0.0, "composition": "storyboard",
    }


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
    storyboard_mode: bool = False,
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

    if storyboard_mode:
        return _storyboard_presentation(plan, document, title=title)

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

        text_color = _resolve_text_color(kind, kind_dna) if kind_dna else (
            "FFFFFF" if kind in ("cover", "section", "closing") else "262626"
        )

        if page.get("title"):
            style: dict[str, Any] = {}
            if text_color:
                style["font"] = {"rgb": text_color}
            components.append(Component(type="title", text=str(page["title"]), style=style))

        if kind == "toc" and section_titles:
            components.append(Component(
                type="body",
                text="\n".join(f"- {name}" for name in section_titles),
            ))

        # try stored components first (zero generation cost)
        source_blocks = [
            block_id for block_id in (page.get("source_blocks") or [])
            if block_id in lookup
            and not (
                kind in ("section", "content")
                and lookup[block_id].type == "heading"
                and (lookup[block_id].text or "").strip().casefold()
                == str(page.get("title") or "").strip().casefold()
            )
        ]
        stored = find_by_kind(archetype, item_count=len(source_blocks))
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
            for block_id in source_blocks:
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
