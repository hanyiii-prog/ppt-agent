"""Deterministic slide design layer.

A semantic slide (purpose + title + supporting points) is composed here into
a fully positioned, fully styled set of drawable primitives. The output is
plain IR, so the native PPTX engine and the HTML engine render byte-identical
designs from a single source of truth.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from .ir import Component, Presentation, Slide
from .styling import slide_size_inches
from .theme import DEFAULT_THEME, Theme, resolve_theme

# Text-bearing component types that carry supporting points.
_POINT_TYPES = frozenset({"text", "paragraph", "body", "bullet", "label", "caption"})
_TITLE_TYPES = frozenset({"title", "heading"})

_PURPOSE_ALIASES: dict[str, str] = {
    "cover": "cover", "封面": "cover", "标题页": "cover", "首页": "cover",
    "agenda": "agenda", "目录": "agenda", "大纲": "agenda",
    "outline": "agenda", "contents": "agenda", "toc": "agenda",
    "closing": "closing", "总结": "closing", "结论": "closing", "谢谢": "closing",
    "结尾": "closing", "summary": "closing", "thanks": "closing", "end": "closing",
    "section": "section", "章节": "section", "chapter": "section", "分隔": "section",
}

# Headings that name a layout rather than carry content: `## 封面` is a marker,
# so the real cover headline comes from the paragraphs underneath it.
_PLACEHOLDER_HEADINGS: frozenset[str] = frozenset({
    "封面", "标题页", "首页", "cover", "title page", "title",
})

# Fraction of an em used by an ASCII glyph, relative to a full-width CJK glyph.
_ASCII_RATIO = 0.52
_CJK_THRESHOLD = 0x2E7F
_LINE_SPACING = 1.34


def normalize_purpose(value: Any) -> str:
    """Map a free-form slide purpose (English or Chinese) onto a design layout."""
    text = str(value or "").strip().lower()
    if not text:
        return "content"
    if text in _PURPOSE_ALIASES:
        return _PURPOSE_ALIASES[text]
    for key, layout in _PURPOSE_ALIASES.items():
        if key in text:
            return layout
    return "content"


def _glyph_ratio(char: str) -> float:
    return 1.0 if ord(char) > _CJK_THRESHOLD else _ASCII_RATIO


def wrap_lines(text: str, width_in: float, font_pt: float) -> list[str]:
    """Greedy wrap measured in em units, so CJK and Latin share one metric."""
    capacity = max(float(width_in), 0.1) * 72.0
    lines: list[str] = []
    for raw in str(text or "").split("\n"):
        segment = raw.strip()
        if not segment:
            lines.append("")
            continue
        current = ""
        used = 0.0
        for char in segment:
            width = font_pt * _glyph_ratio(char)
            if current and used + width > capacity:
                lines.append(current)
                current, used = char, width
            else:
                current += char
                used += width
        lines.append(current)
    return lines or [""]


def text_height(text: Any, width_in: float, font_pt: float, *, pad: float = 0.10, spacing: float = _LINE_SPACING) -> float:
    """Estimated rendered height of a wrapped text block, in inches."""
    lines = wrap_lines(str(text or ""), width_in, font_pt)
    return round(len(lines) * font_pt * spacing / 72.0 + pad, 3)


def _value(component: Any, key: str) -> float | None:
    raw = getattr(component, key, None)
    return float(raw) if isinstance(raw, (int, float)) else None


def _has_geometry(component: Any) -> bool:
    return all(_value(component, key) is not None for key in ("x", "y", "w", "h"))


def is_pre_designed(slide: Any) -> bool:
    """True when a slide already carries explicit geometry (template-injected IR)."""
    return any(_has_geometry(component) for component in (getattr(slide, "components", None) or []))


def _texts(slide: Any) -> tuple[str, list[str]]:
    title = ""
    points: list[str] = []
    for component in getattr(slide, "components", None) or []:
        text = getattr(component, "text", None)
        if text is None and isinstance(getattr(component, "data", None), dict):
            text = component.data.get("text")
        text = str(text or "").strip()
        if not text:
            continue
        ctype = str(getattr(component, "type", "") or "").lower()
        if not title and ctype in _TITLE_TYPES:
            title = text
            continue
        if ctype in _TITLE_TYPES and not title:
            title = text
            continue
        points.append(text)
    if not title:
        title = str(getattr(slide, "claim", "") or "").strip()
    if not title and points:
        title, points = points[0], points[1:]
    return title, points


class SlideDesigner:
    """Compose semantic slides into positioned primitives using one theme."""

    def __init__(self, theme: Theme | None = None, *, width_in: float = 13.333, height_in: float = 7.5):
        self.theme = theme or DEFAULT_THEME
        self.w = float(width_in)
        self.h = float(height_in)
        self.content_w = self.w - 2 * self.theme.margin_x

    # ------------------------------------------------------------------ primitives
    def _rect(
        self,
        cid: str,
        x: float,
        y: float,
        w: float,
        h: float,
        rgb: str | None,
        *,
        shape: str = "rect",
    ) -> Component:
        style: dict[str, Any] = {
            "fill": {"type": "solid", "rgb": rgb} if rgb else {"type": "none"},
        }
        if shape != "rect":
            style["shape"] = shape
        return Component(type="shape", id=cid, x=round(x, 3), y=round(y, 3), w=round(w, 3), h=round(h, 3), style=style)

    def _text(
        self,
        cid: str,
        text: Any,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        size: float,
        rgb: str,
        bold: bool = False,
        align: str = "left",
        font: str | None = None,
    ) -> Component:
        font_style: dict[str, Any] = {
            "size_pt": float(size),
            "rgb": rgb,
            "alignment": align,
            "name": font or self.theme.font_body,
        }
        if bold:
            font_style["bold"] = True
        return Component(
            type="text",
            id=cid,
            text=str(text),
            x=round(x, 3),
            y=round(y, 3),
            w=round(w, 3),
            h=round(h, 3),
            style={"font": font_style},
        )

    def _heading(self, title: str, cid_prefix: str = "head") -> tuple[list[Component], float]:
        """Shared page heading: accent anchor bar + title + short rule."""
        theme = self.theme
        width = self.content_w - 0.42
        height = max(text_height(title, width, theme.slide_title_pt, pad=0.08), 0.68)
        parts = [
            self._rect(f"{cid_prefix}-anchor", theme.margin_x, theme.title_top + 0.06, 0.085, 0.58, theme.accent),
            self._text(
                f"{cid_prefix}-title", title,
                theme.margin_x + 0.30, theme.title_top, width, height,
                size=theme.slide_title_pt, rgb=theme.primary_deep, bold=True, font=theme.font_title,
            ),
        ]
        bottom = theme.title_top + height
        parts.append(self._rect(f"{cid_prefix}-rule", theme.margin_x, bottom + 0.15, 0.95, 0.055, theme.accent))
        return parts, bottom + 0.46

    def _footer(self, index: int, total: int, deck_title: str | None) -> list[Component]:
        theme = self.theme
        parts = [self._rect("footer-rule", theme.margin_x, theme.footer_rule_y, self.content_w, 0.012, theme.line)]
        if deck_title:
            parts.append(self._text(
                "footer-title", deck_title,
                theme.margin_x, theme.footer_text_y, self.content_w * 0.7, 0.32,
                size=theme.footer_pt, rgb=theme.text_muted,
            ))
        parts.append(self._text(
            "footer-page", f"{index:02d} / {total:02d}",
            self.w - theme.margin_x - 1.4, theme.footer_text_y, 1.4, 0.32,
            size=theme.footer_pt, rgb=theme.text_muted, align="right",
        ))
        return parts

    # ------------------------------------------------------------------ layouts
    def _cover(self, title: str, points: Sequence[str], deck_title: str | None) -> list[Component]:
        theme = self.theme
        parts = [
            self._rect("cover-spine", 0.0, 0.0, 0.52, self.h, theme.primary),
            self._rect("cover-spine-accent", 0.52, 0.0, 0.09, self.h, theme.accent),
            self._rect("cover-base", 0.0, self.h - 0.20, self.w, 0.20, theme.primary),
        ]
        x = 1.60
        width = self.w - x - 1.30

        # `## 封面` is a layout marker; the headline lives in the paragraphs.
        body = [point for point in points if point]
        if str(title or "").strip().lower() in _PLACEHOLDER_HEADINGS:
            headline = body[0] if body else (deck_title or "演示文稿")
            body = body[1:]
        else:
            headline = title or (body[0] if body else "") or deck_title or "演示文稿"
            if body and body[0] == headline:
                body = body[1:]

        subtitle = body[0] if body else ""
        meta = body[1] if len(body) > 1 else ""

        title_h = text_height(headline, width, theme.cover_title_pt, pad=0.14)
        sub_h = text_height(subtitle, width, theme.cover_sub_pt) if subtitle else 0.0
        block = 0.075 + 0.36 + title_h + ((0.30 + sub_h) if subtitle else 0.0)
        top = max(1.35, (self.h - block) / 2 - 0.10)

        parts.append(self._rect("cover-rule", x, round(top, 3), 1.45, 0.075, theme.accent))
        parts.append(self._text(
            "cover-title", headline, x, round(top + 0.36, 3), width, title_h,
            size=theme.cover_title_pt, rgb=theme.primary_deep, bold=True, font=theme.font_title,
        ))
        if subtitle:
            parts.append(self._text(
                "cover-sub", subtitle, x, round(top + 0.36 + title_h + 0.30, 3), width, sub_h,
                size=theme.cover_sub_pt, rgb=theme.text_muted,
            ))
        if meta:
            parts.append(self._text(
                "cover-meta", meta, x, self.h - 1.05, width, 0.40,
                size=theme.cover_meta_pt, rgb=theme.text_muted,
            ))
        return parts

    def _agenda(self, title: str, points: Sequence[str], index: int, total: int, deck_title: str | None) -> list[Component]:
        theme = self.theme
        parts, body_top = self._heading(title or "目录", "agenda")
        items = [point for point in points if point]
        if not items:
            parts.extend(self._footer(index, total, deck_title))
            return parts

        available = theme.footer_rule_y - 0.32 - body_top
        count = len(items)
        card_h = max(0.58, min(0.94, available / count - 0.16))
        gap = 0.20 if count == 1 else max(0.14, min(0.34, (available - count * card_h) / (count - 1)))

        cursor = body_top
        for order, item in enumerate(items, 1):
            parts.append(self._rect(f"agenda-row-{order:02d}", theme.margin_x, round(cursor, 3), self.content_w, round(card_h, 3), theme.primary_soft))
            parts.append(self._rect(f"agenda-row-{order:02d}-bar", theme.margin_x, round(cursor, 3), 0.06, round(card_h, 3), theme.accent))
            label_h = 0.42
            label_y = cursor + (card_h - label_h) / 2
            parts.append(self._text(
                f"agenda-row-{order:02d}-no", f"{order:02d}",
                theme.margin_x + 0.30, round(label_y, 3), 0.9, label_h,
                size=theme.agenda_no_pt, rgb=theme.accent, bold=True,
            ))
            parts.append(self._text(
                f"agenda-row-{order:02d}-text", item,
                theme.margin_x + 1.32, round(label_y, 3), self.content_w - 1.65, label_h,
                size=theme.body_pt, rgb=theme.text,
            ))
            cursor += card_h + gap

        parts.extend(self._footer(index, total, deck_title))
        return parts

    def _content(self, title: str, points: Sequence[str], index: int, total: int, deck_title: str | None) -> list[Component]:
        theme = self.theme
        parts, body_top = self._heading(title or deck_title or "", "head")
        items = [point for point in points if point]
        text_w = self.content_w - theme.body_indent - 0.06
        size = theme.body_pt
        line_h = size * _LINE_SPACING / 72.0

        if items:
            heights = [text_height(item, text_w, size) for item in items]
            available = theme.footer_rule_y - 0.30 - body_top
            count = len(items)
            gap = theme.bullet_gap
            if count > 1:
                slack = available - sum(heights)
                gap = max(0.16, min(0.34, slack / (count - 1)))
            elif heights and heights[0] > available:
                # A single very long point: keep the box, let the page gate flag it.
                gap = theme.bullet_gap

            cursor = body_top
            for order, (item, height) in enumerate(zip(items, heights), 1):
                dot = 0.085
                parts.append(self._rect(
                    f"point-{order:02d}-dot",
                    theme.margin_x + 0.07, round(cursor + line_h / 2 - dot / 2, 3), dot, dot,
                    theme.accent, shape="ellipse",
                ))
                parts.append(self._text(
                    f"point-{order:02d}", item,
                    theme.margin_x + theme.body_indent, round(cursor, 3), text_w, height,
                    size=size, rgb=theme.text,
                ))
                cursor += height + gap

        parts.extend(self._footer(index, total, deck_title))
        return parts

    def _section(self, title: str, points: Sequence[str], index: int, total: int, deck_title: str | None) -> list[Component]:
        theme = self.theme
        width = self.w * 0.62
        parts = [
            self._rect("section-band", 0.0, 0.0, 0.30, self.h, theme.primary),
            self._rect("section-accent", 0.30, 0.0, 0.07, self.h, theme.accent),
        ]
        headline = title or deck_title or ""
        title_h = text_height(headline, width, theme.section_title_pt, pad=0.12)
        top = max(2.0, (self.h - title_h) / 2)
        parts.append(self._text(
            "section-title", headline, 1.45, round(top, 3), width, title_h,
            size=theme.section_title_pt, rgb=theme.primary_deep, bold=True, font=theme.font_title,
        ))
        parts.append(self._rect("section-rule", 1.45, round(top + title_h + 0.18, 3), 1.30, 0.07, theme.accent))
        parts.append(self._text(
            "section-page", f"{index:02d} / {total:02d}",
            self.w - theme.margin_x - 1.4, self.h - 0.85, 1.4, 0.32,
            size=theme.footer_pt, rgb=theme.text_muted, align="right",
        ))
        return parts

    def _closing(self, title: str, points: Sequence[str], deck_title: str | None) -> list[Component]:
        theme = self.theme
        parts = [self._rect("closing-bg", 0.0, 0.0, self.w, self.h, theme.primary_deep)]
        headline = title or deck_title or "谢谢"
        width = self.w - 4.0
        x = (self.w - width) / 2

        title_h = text_height(headline, width, theme.closing_title_pt, pad=0.12)
        items = [point for point in points if point]
        body_h = sum(text_height(item, width, theme.closing_body_pt) for item in items)
        body_h += 0.16 * max(0, len(items) - 1)

        block = title_h + 0.30 + (body_h + 0.34 if items else 0.0)
        top = max(1.6, (self.h - block) / 2)

        parts.append(self._rect("closing-rule", round((self.w - 1.20) / 2, 3), round(top - 0.30, 3), 1.20, 0.07, theme.accent))
        parts.append(self._text(
            "closing-title", headline, x, round(top, 3), width, title_h,
            size=theme.closing_title_pt, rgb=theme.text_inverse, bold=True, align="center", font=theme.font_title,
        ))
        cursor = top + title_h + 0.34
        for order, item in enumerate(items, 1):
            height = text_height(item, width, theme.closing_body_pt)
            parts.append(self._text(
                f"closing-point-{order:02d}", item, x, round(cursor, 3), width, height,
                size=theme.closing_body_pt, rgb=theme.text_inverse, align="center",
            ))
            cursor += height + 0.16
        return parts

    # ------------------------------------------------------------------ entry point
    def design(self, slide: Any, *, index: int, total: int, deck_title: str | None = None) -> Slide:
        purpose = normalize_purpose(getattr(slide, "purpose", None))
        title, points = _texts(slide)

        if purpose == "cover":
            components = self._cover(title, points, deck_title)
        elif purpose == "agenda":
            components = self._agenda(title, points, index, total, deck_title)
        elif purpose == "section":
            components = self._section(title, points, index, total, deck_title)
        elif purpose == "closing":
            components = self._closing(title, points, deck_title)
        else:
            components = self._content(title, points, index, total, deck_title)

        data = slide.data if isinstance(getattr(slide, "data", None), dict) else {}
        if purpose == "closing":
            data = {**data, "background": {"fill": {"type": "solid", "rgb": self.theme.primary_deep}}}

        return Slide(
            id=getattr(slide, "id", "") or f"slide-{index:02d}",
            purpose=purpose,
            claim=getattr(slide, "claim", None),
            layout=getattr(slide, "layout", None),
            components=components,
            speaker_notes=getattr(slide, "speaker_notes", None),
            data=data,
        )


def design_presentation(presentation: Presentation, theme: str | Theme | None = None) -> Presentation:
    """Return a copy of ``presentation`` with every semantic slide composed.

    Slides that already carry explicit geometry (template DNA path) are passed
    through untouched — they were designed by the template, not by us.
    """
    width_in, height_in = slide_size_inches(presentation)
    declared = presentation.theme if isinstance(presentation.theme, dict) else {}
    resolved = resolve_theme(theme or declared.get("name"))
    if isinstance(declared, dict):
        resolved = resolved.with_overrides({k: v for k, v in declared.items() if k != "name"})
    designer = SlideDesigner(resolved, width_in=width_in, height_in=height_in)

    total = len(presentation.slides)
    slides: list[Slide] = []
    for index, slide in enumerate(presentation.slides, 1):
        if is_pre_designed(slide):
            slides.append(slide)
            continue
        slides.append(designer.design(slide, index=index, total=total, deck_title=presentation.title))

    return Presentation(
        version=presentation.version,
        title=presentation.title,
        slides=slides,
        audience=presentation.audience,
        objective=presentation.objective,
        theme={**declared, "name": resolved.name},
        sources=list(presentation.sources or []),
    )
