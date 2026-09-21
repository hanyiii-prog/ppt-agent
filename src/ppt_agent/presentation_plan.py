"""Presentation Plan: content -> an ordered, kind-labelled page plan.

The plan is the contract between the understanding layer (3.B) and the
generation layer (3.C): a list of pages, each with a page kind that matches
the five DNA page kinds (cover / toc / section / content / closing), a title
and the ``source_block`` ids it must carry (traceability both ways).

Deterministic rules -- no LLM:
* H1 before any section -> cover (title + first paragraph/bullets as subtitle)
* every level<=2 heading -> one section page; its children fill content pages
* tables always start a fresh content page (they do not share)
* leftover blocks paginate by char capacity (from ``page_count`` assumptions)
* closing page appended; the plan reconciles with ``estimate_page_count``
"""

from __future__ import annotations

from typing import Any

from .content_ir import ContentBlock, ContentDocument
from .page_count import estimate_page_count

SCHEMA = "presentation-plan/v1"

_CHARS_PER_PAGE = 260.0
_DENSITY: dict[str, float] = {"compact": 1.3, "standard": 1.0, "air": 0.75}


def page_capacity(density: str = "standard") -> float:
    """Character budget of one page at ``density`` (public, single-sourced).

    Callers that paginate their own units (the clone planner, which must keep
    tables atomic and cards whole) need the same number this module reasons on;
    keeping one function avoids two drifting capacities.
    """
    factor = _DENSITY.get(density)
    if factor is None:
        raise ValueError(f"unknown density {density!r}; use compact|standard|air")
    return _CHARS_PER_PAGE * factor


def build_presentation_plan(
    document: ContentDocument, *, density: str = "standard"
) -> dict[str, Any]:
    """ContentDocument -> presentation plan dict."""
    capacity = page_capacity(density)

    pages: list[dict[str, Any]] = []

    def add_page(kind: str, title: str | None, blocks: list, **extra: Any) -> None:
        entry: dict[str, Any] = {
            "page_no": len(pages) + 1,
            "kind": kind,
            "title": title,
            "source_blocks": [block.id for block in blocks],
            **extra,
        }
        pages.append(entry)

    blocks = list(document.blocks)
    index = 0

    # cover: an H1 (or the document title) + optional subtitle block
    cover_title = document.title
    cover_subtitle: list = []
    if blocks and blocks[0].type == "heading" and (blocks[0].level or 1) == 1:
        cover_title = cover_title or blocks[0].text
        index = 1
        while index < len(blocks) and blocks[index].type in ("paragraph", "bullets", "quote"):
            if blocks[index].char_volume() <= capacity:
                cover_subtitle.append(blocks[index])
                index += 1
            else:
                break
    add_page("cover", cover_title, cover_subtitle)

    sections = document.sections()
    # level-1 headings are cover material (already consumed above)
    content_sections = [
        (heading, children)
        for heading, children in sections
        if (heading.level or 1) >= 2
    ]

    toc_added = False
    for heading, children in content_sections:
        if len(content_sections) >= 2 and not toc_added:
            add_page("toc", "目录", [])
            toc_added = True
        add_page("section", heading.text, [heading])

        # tables paginate standalone
        remaining: list = []
        for block in children:
            if block.type == "table":
                if remaining:
                    _add_content_pages(add_page, heading, remaining, capacity)
                    remaining = []
                add_page("content", heading.text, [block], note="table page")
            else:
                remaining.append(block)
        _add_content_pages(add_page, heading, remaining, capacity)

    add_page("closing", "谢谢", [])

    estimate = estimate_page_count(document, density=density)
    return {
        "schema": SCHEMA,
        "density": density,
        "pages": pages,
        "page_total": len(pages),
        "estimate_reference": {
            "estimated_total": estimate["total"],
            "delta_vs_plan": len(pages) - estimate["total"],
        },
        "metadata": {"llm": "off", "planner": "rules"},
    }


def _title_body_units(blocks: list) -> list[list]:
    """Group a block stream into atomic units so a card title is never
    paginated away from the body that follows it.

    The markdown parser emits a short *title* block (a heading, or a one-item
    list such as ``1. 破局思路``) immediately followed by its *body* block (a
    paragraph or a multi-item list). Packing them individually let the greedy
    page splitter drop the orphaned title onto the last card of one page while
    its body landed on the next page -- producing title-only cards with an
    empty body (the "blank control" defect). Binding title+body into one unit
    keeps every card whole. Tables and unpaired blocks form their own unit.
    """
    units: list[list] = []
    i, n = 0, len(blocks)
    while i < n:
        b = blocks[i]
        if b.type == "table":
            units.append([b])
            i += 1
            continue
        is_list = b.type in ("bullets", "ordered")
        single_item = is_list and bool(getattr(b, "items", None)) and len(b.items) == 1
        title_text = ""
        if b.type == "heading":
            title_text = (b.text or "").strip()
        elif single_item:
            title_text = b.items[0].strip()

        is_title = (
            bool(title_text)
            and len(title_text) <= 26
            and not any(c in title_text for c in "：:。.;；")
        )
        if is_title and i + 1 < n:
            nb = blocks[i + 1]
            has_body = (nb.type == "paragraph" and bool((nb.text or "").strip())) or (
                nb.type in ("bullets", "ordered") and bool(getattr(nb, "items", None))
            )
            if has_body:
                units.append([b, nb])
                i += 2
                continue
        units.append([b])
        i += 1
    return units


def _add_content_pages(add_page, heading, blocks: list, capacity: float) -> None:
    """Greedy pagination of non-table blocks into content pages.

    Units are whole title+body pairs (see :func:`_title_body_units`), so a
    card's heading and its description always land on the same page.
    """
    if not blocks:
        return
    current: list = []
    volume = 0.0
    for unit in _title_body_units(blocks):
        unit_volume = sum(bl.char_volume() for bl in unit)
        if current and volume + unit_volume > capacity:
            add_page("content", heading.text, current)
            current, volume = [], 0.0
        current.extend(unit)
        volume += unit_volume
    if current:
        add_page("content", heading.text, current)


__all__ = ["SCHEMA", "build_presentation_plan", "page_capacity"]
