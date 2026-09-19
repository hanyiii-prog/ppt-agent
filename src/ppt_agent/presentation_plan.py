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

from .content_ir import ContentDocument
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


def _add_content_pages(add_page, heading, blocks: list, capacity: float) -> None:
    """Greedy pagination of non-table blocks into content pages."""
    if not blocks:
        return
    current: list = []
    volume = 0.0
    for block in blocks:
        block_volume = block.char_volume()
        if current and volume + block_volume > capacity:
            add_page("content", heading.text, current)
            current, volume = [], 0.0
        current.append(block)
        volume += block_volume
    if current:
        add_page("content", heading.text, current)


__all__ = ["SCHEMA", "build_presentation_plan", "page_capacity"]
