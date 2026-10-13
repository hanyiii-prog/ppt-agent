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
    "architecture", "responsibility", "staffing", "matrix",
)

_METRIC = re.compile(r"\d+\.\d+%|\d+%|\d{2,}")
_DATEISH = re.compile(
    r"(\d{1,2}[./月]\d{1,2}|第[一二三四五六七八九十\d]+[步阶段轮周月]|^\d{4}年?|\d+月)"
)
_CONTRAST = re.compile(r"(对比|对照|VS|vs|versus|相较于|相比之下)")
_PARALLEL = 4  # bullet count that starts looking like a grid


def classify_table_semantics(block: ContentBlock) -> str:
    """Classify a table by its information job, not its visual shape.

    A generic ``table_page`` decision is too weak for executive decks: the
    same table renderer cannot express a five-layer architecture, a schedule,
    and a responsibility matrix. This classifier stays content-driven so the
    renderer can choose a matching editable composition without hard-coding a
    customer's template.
    """
    hinted = str((block.analysis or {}).get("table_role") or "").strip().lower()
    aliases = {
        "hierarchy": "architecture",
        "architecture": "architecture",
        "schedule": "timeline",
        "timeline": "timeline",
        "responsibility": "responsibility",
        "raci": "responsibility",
        "people": "staffing",
        "staffing": "staffing",
        "comparison": "comparison",
        "matrix": "matrix",
        "table": "matrix",
    }
    if hinted in aliases:
        return aliases[hinted]

    headers = " ".join(str(value or "") for value in block.headers)
    rows = [" ".join(str(value or "") for value in row) for row in block.rows]
    header_text = headers.lower()
    first_column = [row[0].strip() for row in block.rows if row]
    # The fallback is intentionally structural. It does not depend on a
    # customer's people, products, or industry vocabulary.
    if any(token in header_text for token in (
        "层级", "level", "layer", "hierarchy", "架构", "structure",
    )):
        return "architecture"
    if any(token in header_text for token in (
        "时间", "日期", "阶段", "time", "date", "period", "milestone",
    )):
        return "timeline"
    if any(token in header_text for token in (
        "责任", "负责人", "责任主体", "owner", "role", "responsible",
        "raci", "accountable",
    )):
        return "responsibility"
    if any(token in header_text for token in (
        "人员", "姓名", "岗位", "person", "people", "staff", "name",
    )):
        return "staffing"
    if any(token in header_text for token in (
        "步骤", "step", "phase",
    )) and len(block.rows) <= 8:
        return "timeline"
    if len(block.headers) == 2 and len(block.rows) >= 2:
        left_values = [value for value in first_column if value]
        if len(left_values) == len(block.rows):
            return "comparison"
    marker_cells = [
        value.strip().upper()
        for row in block.rows
        for value in row[1:]
        if value and value.strip()
    ]
    if marker_cells:
        marker_ratio = sum(
            1 for value in marker_cells
            if value in {"R", "A", "C", "I", "D", "P", "O", "X", "-", "N/A"}
        ) / len(marker_cells)
        if marker_ratio >= 0.55 and len(block.headers) >= 3:
            return "responsibility"
    return "matrix"


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
        semantic = classify_table_semantics(tables[0])
        archetype = "table_page" if semantic == "matrix" else semantic
        return {
            "schema": SCHEMA,
            "archetype": archetype,
            "confidence": 0.95,
            "reason": f"table semantics: {semantic}; tables never share pages",
        }

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
        existing = page.get("archetype")
        if (
            isinstance(existing, dict)
            and existing.get("archetype") in ARCHETYPES
        ):
            continue
        blocks = _blocks_of(document, page.get("source_blocks") or [])
        page["archetype"] = select_archetype(blocks)
    annotated["metadata"] = {
        **(annotated.get("metadata") or {}),
        "archetypes": SCHEMA,
    }
    return annotated
