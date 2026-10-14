from __future__ import annotations

from typing import Any

from .evidence_graph import EvidenceGraph
from .editability import PROHIBITED_IMAGE_TYPES
from .ir import Component, Presentation, Provenance, Slide


def compile_presentation(
    design_ir: dict[str, Any],
    evidence: EvidenceGraph | dict[str, Any],
    *,
    slide_size: tuple[float, float] = (13.333, 7.5),
) -> Presentation:
    """Compile the Page Design IR into Universal Presentation IR."""
    from .editability import validate_presentation_editability

    theme = design_ir.get("theme") or {}
    colors = theme.get("colors") or {}
    fonts = theme.get("fonts") or {}
    scale = theme.get("type_scale") or {}
    slides = [
        compile_slide(page, colors, fonts, scale, evidence, slide_size=slide_size)
        for page in design_ir.get("pages") or []
    ]
    presentation = Presentation(
        version="0.1",
        title=str(design_ir.get("title") or "Presentation"),
        slides=slides,
        theme={
            "slide_size_inches": {"width": slide_size[0], "height": slide_size[1]},
            **theme,
        },
    )
    report = validate_presentation_editability(presentation)
    if not report["passed"]:
        issues = [issue for page in report["pages"] for issue in page["issues"]]
        raise ValueError("; ".join(issues))
    return presentation


def compile_slide(
    page: dict[str, Any],
    colors: dict[str, str],
    fonts: dict[str, str],
    scale: dict[str, Any],
    evidence: EvidenceGraph | dict[str, Any],
    *,
    slide_size: tuple[float, float] = (13.333, 7.5),
) -> Slide:
    kind = str(page.get("kind") or "content")
    width, height = slide_size
    slots = page.get("slots") or {}
    title_font = str(fonts.get("title", "Segoe UI"))
    body_font = str(fonts.get("body", "Segoe UI"))
    components: list[Component] = []

    def font_size(value: Any, default: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return default
        return float(value)

    def text(
        component_type: str,
        slot: dict[str, Any],
        *,
        default_size: float,
    ) -> Component | None:
        value = str(slot.get("value") or "").strip()
        if not value:
            return None
        font_name = title_font if component_type in {"title", "heading", "subtitle"} else body_font
        return Component(
            type=component_type,
            id=f"{page['page_id']}-{slot.get('id', component_type)}",
            x=float(slot.get("x", 0.8)),
            y=float(slot.get("y", 0.8)),
            w=float(slot.get("w", width - 1.6)),
            h=float(slot.get("h", 0.8)),
            text=value,
            style={
                "font": {
                    "name": font_name,
                "size_pt": font_size(
                    slot.get("size_pt") or scale.get(str(slot.get("font"))),
                    default_size,
                ),
                    "rgb": colors.get(str(slot.get("color")), "1F2937"),
                    "bold": bool(slot.get("bold", False)),
                    "alignment": "center" if kind == "closing" else "left",
                },
            },
        )

    def rect(slot: dict[str, Any]) -> Component | None:
        return Component(
            type="shape",
            id=f"{page['page_id']}-{slot.get('id', 'rect')}",
            x=float(slot.get("x", 0.0)),
            y=float(slot.get("y", 0.0)),
            w=float(slot.get("w", width)),
            h=float(slot.get("h", 0.1)),
            style={"fill": {"rgb": colors.get(str(slot.get("color")), "DDE5EC")}},
        )

    for slot in slots.values():
        slot_id = str(slot.get("id") or "")
        slot_kind = str(slot.get("kind") or "").lower()
        if slot_kind in PROHIBITED_IMAGE_TYPES:
            raise ValueError(
                f"page {page['page_id']} slot {slot_id!r} is {slot_kind!r}; "
                "generated slide content must be native and editable"
            )
        if slot_kind == "rect":
            component = rect(slot)
        elif slot_id == "table":
            component = _table_component(page, slot, evidence)
        elif slot_id == "title" and kind in {"cover", "closing"}:
            component = text("title", slot, default_size=font_size(scale.get("cover_title"), 44))
        elif slot_id == "title":
            component = text("title", slot, default_size=font_size(scale.get("title"), 30))
        elif slot_id == "subtitle":
            component = text("subtitle", slot, default_size=font_size(scale.get("takeaway"), 20))
        elif slot_id == "takeaway":
            component = text("body", slot, default_size=font_size(scale.get("takeaway"), 20))
        elif slot_id == "body":
            component = text("body", slot, default_size=font_size(scale.get("body"), 18))
        else:
            component = text("label", slot, default_size=font_size(scale.get("meta"), 12))
        if component is not None:
            components.append(component)

    visual = str(page.get("visual_form") or "").lower()
    if any(name in visual for name in ("progress", "timeline", "flow", "sequence")):
        components.extend(_progress_dots(page, colors, fonts, scale, width))

    if not components:
        raise ValueError(f"page {page.get('page_id')} compiled to no components")
    return Slide(
        id=str(page["page_id"]),
        purpose=kind,
        claim=str(page.get("title") or ""),
        layout=str(page.get("composition") or kind),
        components=components,
        speaker_notes=str(page.get("speaker_notes") or ""),
        data={"background": {"fill": {"rgb": colors.get("surface", "FFFFFF")}}}
        if kind not in {"cover", "closing"} else {},
    )


def _table_component(
    page: dict[str, Any],
    slot: dict[str, Any],
    evidence: EvidenceGraph | dict[str, Any],
) -> Component:
    table = slot.get("value") or {}
    rows = [table.get("headers") or []] + list(table.get("rows") or [])
    return Component(
        type="table",
        id=f"{page['page_id']}-table",
        x=float(slot.get("x", 0.8)),
        y=float(slot.get("y", 2.4)),
        w=float(slot.get("w", 11.7)),
        h=float(slot.get("h", 2.4)),
        data={"rows": rows},
        provenance=_provenance(page, evidence),
    )


def _progress_dots(
    page: dict[str, Any],
    colors: dict[str, str],
    fonts: dict[str, str],
    scale: dict[str, Any],
    width: float,
) -> list[Component]:
    components: list[Component] = []
    accent = colors.get("accent", "C6602D")
    muted = colors.get("muted", "555555")
    meta_size = float(scale.get("meta") or 12)
    for index in range(4):
        x = 1.4 + index * ((width - 2.4) / 4)
        components.append(Component(
            type="shape", id=f"{page['page_id']}-dot-{index + 1:02d}",
            x=x, y=6.61, w=0.2, h=0.2,
            style={"fill": {"rgb": accent}, "shape": "ellipse"},
        ))
        components.append(Component(
            type="label", id=f"{page['page_id']}-stage-{index + 1:02d}",
            x=x + 0.3, y=6.82, w=1.5, h=0.35,
            text=f"Stage {index + 1}",
            style={"font": {"name": fonts.get("body", "Segoe UI"), "size_pt": meta_size, "rgb": muted}},
        ))
    return components


def _provenance(
    page: dict[str, Any],
    evidence: EvidenceGraph | dict[str, Any],
) -> list[Provenance]:
    facts = evidence.facts if isinstance(evidence, EvidenceGraph) else evidence.get("facts") or []
    fact_by_block = {
        block_id: fact
        for fact in facts
        for block_id in fact.get("source_block_ids") or []
    }
    result: list[Provenance] = []
    for block in page.get("blocks") or []:
        fact = fact_by_block.get(block.get("id"))
        result.append(Provenance(
            source_id=str(block.get("source_id") or "source"),
            locator=str(block.get("id") or ""),
            quote=str(fact.get("claim") or "") if fact else _block_text(block),
        ))
    return result


def _block_text(block: dict[str, Any]) -> str:
    if block.get("type") == "table":
        rows = [block.get("headers") or []] + list(block.get("rows") or [])
        return " | ".join(" / ".join(str(cell) for cell in row) for row in rows if row)
    if block.get("items"):
        return "; ".join(str(item) for item in block["items"])
    return str(block.get("text") or "")


__all__ = ["compile_presentation", "compile_slide"]
