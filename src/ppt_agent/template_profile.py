from __future__ import annotations

from pathlib import Path
from typing import Any

from .template_library import _page_families

SCHEMA = "template-profile/v1"


def profile_from_template_dna(dna: dict[str, Any], source: str | Path) -> dict[str, Any]:
    """Turn a user PPTX template into a temporary, task-only profile."""
    from .theme import theme_from_dna

    theme = theme_from_dna(dna, name=f"template:{Path(source).stem}")
    theme_dict = theme.to_dict()
    colors = {
        "primary": theme.primary,
        "primary_deep": theme.primary_deep,
        "accent": theme.accent,
        "surface": theme.primary_soft,
        "panel": theme.accent_soft,
        "text": theme.text,
        "muted": theme.text_muted,
        "inverse": theme.text_inverse,
        "line": theme.line,
    }
    fonts = {"title": theme.font_title, "body": theme.font_body}
    scale = {
        "cover_title": theme.cover_title_pt,
        "title": theme.slide_title_pt,
        "takeaway": theme.section_title_pt,
        "body": theme.body_pt,
        "meta": theme.footer_pt,
    }
    profile = {
        "schema": SCHEMA,
        "id": f"user:{Path(source).stem}",
        "display_name": Path(source).stem,
        "source_kind": "user",
        "source_path": str(source),
        "slide_size": _slide_size(dna),
        "theme": {
            "colors": colors,
            "fonts": fonts,
            "type_scale": scale,
            "spacing": theme_dict.get("spacing", {}),
        },
        "page_families": _page_families("user"),
        "assets": [],
        "quality": {"validated": True, "render_status": "not_rendered"},
        "provenance": {
            "created_by": "user",
            "license_status": "task-only",
            "template_dna_schema": dna.get("schema"),
        },
        "selection": {"score": 1.0, "reasons": ["user template supplied"], "fallbacks": []},
    }
    return profile


def user_template_page_plan(slide_specs: list[Any]) -> list[dict[str, Any]]:
    """Convert V3 SlideSpecs into CloneShell page specs without changing facts."""
    pages: list[dict[str, Any]] = []
    for spec in slide_specs:
        item = spec.to_dict() if hasattr(spec, "to_dict") else dict(spec)
        kind = str(item.get("kind") or "content").lower()
        if kind in {"cover", "closing", "section", "toc"}:
            page = {
                "role": kind,
                "title": str(item.get("title") or ""),
            }
            if kind == "cover":
                page.update({"pill": "", "meta": str(item.get("purpose") or "")})
            elif kind == "closing":
                page.update({"sub": str(item.get("takeaway") or ""), "meta": ""})
            elif kind == "toc":
                page.update({"items": [], "note": ""})
            else:
                page.update({"meta": str(item.get("takeaway") or ""), "lines": []})
            pages.append(page)
            continue

        content = item.get("content") or {}
        cards: list[dict[str, Any]] = []
        for index, metric in enumerate(content.get("metrics") or [], 1):
            cards.append({
                "title": str(metric.get("label") or f"Metric {index}"),
                "lines": [str(metric.get("value") or "")],
            })
        for index, entry in enumerate(content.get("items") or [], 1):
            text = str(entry.get("text") or "").strip()
            if text:
                cards.append({"title": text[:80], "lines": [text]})
        table = content.get("table") or {}
        for row in table.get("rows") or []:
            title = str(row[0] if row else "").strip()
            body = " / ".join(str(cell) for cell in row[1:] if str(cell).strip())
            cards.append({"title": title or "Data row", "lines": [body] if body else []})
        if not cards:
            text = str(content.get("lead") or item.get("takeaway") or "").strip()
            cards.append({"title": text[:80] or "Key message", "lines": [text]})
        cards = cards[:8]
        count = len(cards)
        pages.append({
            "role": "content",
            "kit": "column_cards",
            "title": str(item.get("title") or ""),
            "lead": str(content.get("lead") or item.get("takeaway") or ""),
            "cards": cards,
            "cols": min(4, max(2, count)),
        })
    return pages


def _slide_size(dna: dict[str, Any]) -> list[float]:
    presentation = dna.get("presentation") if isinstance(dna.get("presentation"), dict) else {}
    width = presentation.get("slide_width")
    height = presentation.get("slide_height")
    if isinstance(width, (int, float)) and isinstance(height, (int, float)):
        return [round(float(width), 3), round(float(height), 3)]
    return [13.333, 7.5]


__all__ = ["SCHEMA", "profile_from_template_dna", "user_template_page_plan"]
