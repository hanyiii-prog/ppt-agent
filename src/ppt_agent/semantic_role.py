"""Semantic role labelling for template DNA element records.

Why this exists
---------------
V2.0 DNA knows *what* every shape is (sp / pic / grpSp / table …) but not
*what it means*. "Which of these shapes is the logo?" is answerable by a human
in one glance and by a generator only after the answer is written down.

Roles
-----
``title / subtitle / body / list / logo / image / card / decoration /
header / footer / page_number / table / chart / group / unknown``

Rules run strongest-signal-first: placeholder type beats name hints beat
element kind beats text heuristics beats geometry. Nothing guesses beyond
what the record carries; leftovers stay ``unknown``.

``annotate_deck_dna`` attaches ``semantic_role`` to every element record
(slides layers, master shapes, and the page-kind ornament/frequent tables)
without touching any existing field.
"""

from __future__ import annotations

import copy
import re
from typing import Any

SEMANTIC_ROLES: tuple[str, ...] = (
    "title", "subtitle", "body", "list", "logo", "image", "card",
    "decoration", "header", "footer", "page_number", "table", "chart",
    "group", "unknown",
)

_PLACEHOLDER_MAP: dict[str, str] = {
    "TITLE": "title",
    "CENTER_TITLE": "title",
    "CENTERED_TITLE": "title",
    "SUBTITLE": "subtitle",
    "BODY": "body",
    "OBJECT": "body",
    "TEXT": "body",
    "VERTICAL_BODY": "body",
    "VERTICAL_OBJECT": "body",
    "HEADER": "header",
    "FOOTER": "footer",
    "DATE": "footer",
    "SLIDE_NUMBER": "page_number",
}

_NAME_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"logo|标识|徽标", re.IGNORECASE), "logo"),
    (re.compile(r"page\s*number|页码|pagenum", re.IGNORECASE), "page_number"),
    (re.compile(r"footer|页脚", re.IGNORECASE), "footer"),
    (re.compile(r"header|页眉", re.IGNORECASE), "header"),
    (re.compile(r"deco|ornament|装饰|bg|background|背景", re.IGNORECASE), "decoration"),
)

_TITLE_TEXT = re.compile(
    r"(目\s*录|CONTENTS|Agenda|第[一二三四五六七八九十百]+[章节部分]|Part\s*\d+)", re.IGNORECASE
)

# a shape smaller than this share of the slide is "small" (decoration-sized)
_GLYPH_AREA = 0.018


def _text_of(record: dict[str, Any]) -> str:
    text = record.get("text") or {}
    if isinstance(text, dict):
        return str(text.get("text") or "")
    return ""


def _max_font_pt(record: dict[str, Any]) -> float:
    text = record.get("text") or {}
    if not isinstance(text, dict):
        return 0.0
    sizes = [float(font.get("size_pt") or 0) for font in text.get("fonts") or []]
    return max(sizes) if sizes else 0.0


def _area(record: dict[str, Any], slide_area: float) -> float:
    geometry = record.get("geometry") or {}
    width, height = geometry.get("width"), geometry.get("height")
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
        return 0.0
    if slide_area <= 0:
        return 0.0
    return (float(width) * float(height)) / slide_area


def infer_semantic_role(
    record: dict[str, Any], *, page_kind: str | None = None, slide_area: float = 100.0
) -> str:
    """One element record -> one semantic role (never raises)."""
    placeholder = record.get("placeholder") or {}
    mapped = _PLACEHOLDER_MAP.get(str(placeholder.get("type") or "").upper())
    if mapped:
        return mapped

    name = str(record.get("name") or "")
    for pattern, role in _NAME_RULES:
        if pattern.search(name):
            return role

    element = str(record.get("element") or "")
    if element == "pic":
        return "image"
    if element == "graphicFrame" or record.get("table"):
        return "table"
    if "chart" in element or element == "chart":
        return "chart"
    if record.get("is_group") or element == "grpSp":
        return "group"

    text = _text_of(record)
    if text:
        if _TITLE_TEXT.search(text):
            return "title"
        if _max_font_pt(record) >= 20.0:
            return "title"
        if _max_font_pt(record) >= 12.0:
            return "body"
        return "footer" if page_kind in ("cover", "content") and _area(record, slide_area) < _GLYPH_AREA else "body"

    area = _area(record, slide_area)
    style = record.get("style") or {}
    fill = style.get("fill") or {}
    alpha = fill.get("alpha")
    if area < _GLYPH_AREA or (isinstance(alpha, (int, float)) and alpha < 40):
        return "decoration"
    if area > 0.5:
        return "decoration"  # full-bleed wash
    return "unknown"


def annotate_deck_dna(deck_dna: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy with ``semantic_role`` added to every element record."""
    size = (deck_dna.get("presentation") or {}).get("slide_size_inches") or {}
    slide_area = float(size.get("width") or 13.333) * float(size.get("height") or 7.5)
    annotated = copy.deepcopy(deck_dna)

    def _tag(records: list[Any], page_kind: str | None) -> None:
        for record in records:
            if isinstance(record, dict):
                record["semantic_role"] = infer_semantic_role(
                    record, page_kind=page_kind, slide_area=slide_area
                )
                if record.get("children"):
                    _tag(record["children"], page_kind)

    for page in annotated.get("slides") or []:
        kind = str(page.get("kind")) if page.get("kind") is not None else None
        _tag(page.get("layers") or [], kind)
        _tag(page.get("shapes") or [], kind)

    for master in annotated.get("masters") or []:
        _tag(master.get("shapes") or [], None)

    for kind_dna in (annotated.get("page_kinds") or {}).values():
        if not isinstance(kind_dna, dict):
            continue
        for entry in (kind_dna.get("ornaments") or []) + (kind_dna.get("frequent") or []):
            if isinstance(entry, dict):
                entry["semantic_role"] = infer_semantic_role(entry, slide_area=slide_area)
    return annotated
