"""Page Archetype library: which page *shape* fits which content.

Why this exists
---------------
The generation layer needs a routing decision before it draws: is this page a
bullet list, a card grid, a KPI strip, a timeline, a table? V2.0 shipped five
design-layer layouts (``design.py``) and eight clone-route page kits
(``page_kits.py``), but nothing maps *content* onto them. This module is that
map: a deterministic archetype selector over the analyzer's per-block output
(category / importance / keywords) -- no LLM involved.

Archetypes
----------
``title_bullets``   title + bullet list (the default, always safe)
``cards_grid``      parallel bullets of similar shape -> card grid
``metrics_row``     hard-number bullets -> KPI strip
``table_page``      a table block -> table page (tables never share pages)
``timeline``        ordered items with date/step markers -> timeline
``comparison``      explicit contrast markers (对比 / vs / VS / 对照)
``narrative``       prose paragraph -> narrative page

``select_archetype`` returns the decision *with its reason*; ``annotate_plan``
stamps the archetype onto every content page of a Presentation Plan (a copy
-- the plan itself is never mutated). Cloning-route kits are wired at batch 7;
the archetype name is the contract between plan and generator.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .content_ir import ContentBlock, ContentDocument

SCHEMA = "archetype/v1"

ARCHETYPES: tuple[str, ...] = (
    "title_bullets", "cards_grid", "metrics_row", "table_page",
    "timeline", "comparison", "narrative", "quote_strip",
)

_METRIC = re.compile(r"\d+\.\d+%|\d+%|\d{2,}")
_DATEISH = re.compile(
    r"(\d{1,2}[./月]\d{1,2}|第[一二三四五六七八九十\d]+[步阶段轮周月]|^\d{4}年?|\d+月)"
)
_CONTRAST = re.compile(r"(对比|对照|VS|vs|versus|相较于|相比之下)")
_PARALLEL = 4  # bullet count that starts looking like a grid


def _blocks_of(document: ContentDocument, block_ids: list[str]) -> list[ContentBlock]:
    lookup = {block.id: block for block in document.blocks}
    return [lookup[block_id] for block_id in block_ids if block_id in lookup]


def select_archetype(blocks: list[ContentBlock]) -> dict[str, Any]:
    """One page's blocks -> archetype decision with an explicit reason."""
    if not blocks:
        return {"schema": SCHEMA, "archetype": "title_bullets", "confidence": 0.3,
                "reason": "no content blocks; safe default"}

    tables = [b for b in blocks if b.type == "table"]
    if tables:
        return {"schema": SCHEMA, "archetype": "table_page", "confidence": 0.95,
                "reason": f"{len(tables)} table block(s); tables never share pages"}

    quotes = [b for b in blocks if b.type == "quote"]
    if quotes and len(quotes) >= max(1, len(blocks) - 1):
        return {"schema": SCHEMA, "archetype": "quote_strip", "confidence": 0.7,
                "reason": "page is dominated by quote blocks"}

    bullets: list[str] = []
    for block in blocks:
        if block.type in ("bullets", "ordered"):
            bullets.extend(block.items)
    analysis_text = " ".join(
        (block.text or "") + " " + " ".join(block.items) for block in blocks
    )

    ordered = [b for b in blocks if b.type == "ordered"]
    if ordered and sum(1 for item in bullets if _DATEISH.search(item)) >= max(2, len(bullets) // 2):
        return {"schema": SCHEMA, "archetype": "timeline", "confidence": 0.85,
                "reason": "ordered items carry date/step markers"}

    if _CONTRAST.search(analysis_text) and len(bullets) >= 2:
        return {"schema": SCHEMA, "archetype": "comparison", "confidence": 0.75,
                "reason": "explicit contrast marker in content"}

    hard_metrics = sum(1 for item in bullets if _METRIC.search(item))
    if hard_metrics >= 2 and len(bullets) <= 6:
        return {"schema": SCHEMA, "archetype": "metrics_row", "confidence": 0.8,
                "reason": f"{hard_metrics} bullets carry hard numbers"}

    if len(bullets) >= _PARALLEL:
        lengths = [len(item) for item in bullets]
        spread = (max(lengths) - min(lengths)) / max(1, max(lengths))
        if spread <= 0.8:
            return {"schema": SCHEMA, "archetype": "cards_grid", "confidence": 0.7,
                    "reason": f"{len(bullets)} parallel bullets of similar shape"}

    prose = [b for b in blocks if b.type == "paragraph"]
    if prose and not bullets:
        return {"schema": SCHEMA, "archetype": "narrative", "confidence": 0.6,
                "reason": "prose only"}

    return {"schema": SCHEMA, "archetype": "title_bullets", "confidence": 0.5,
            "reason": "mixed or light content; default list layout"}


def annotate_plan(plan: dict[str, Any], document: ContentDocument) -> dict[str, Any]:
    """Return a copy of a Presentation Plan with per-page ``archetype`` hints.

    Only ``content`` pages get an archetype; cover / toc / section / closing
    keep their fixed kinds. The input plan is never mutated.
    """
    annotated = copy.deepcopy(plan)
    for page in annotated.get("pages", []):
        if page.get("kind") != "content":
            continue
        blocks = _blocks_of(document, page.get("source_blocks") or [])
        page["archetype"] = select_archetype(blocks)
    annotated["metadata"] = {
        **(annotated.get("metadata") or {}),
        "archetypes": SCHEMA,
    }
    return annotated
