"""Extract bounded, non-executable design context from an HTML reference."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

_DIAGRAM_CLASS_WORDS = (
    "arch", "diagram", "flow", "model", "pipeline", "chart", "stage", "node",
)


class _ReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.headings: list[str] = []
        self.text: list[str] = []
        self.diagram: list[str] = []
        self._skip_depth = 0
        self._title_depth = 0
        self._heading_depth = 0
        self._diagram_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._title_depth += 1
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_depth += 1
        class_names = str(values.get("class") or "").lower()
        if any(word in class_names for word in _DIAGRAM_CLASS_WORDS):
            self._diagram_tags.append(tag)
        for key in ("alt", "aria-label", "data-label"):
            label = _normalize(values.get(key))
            if label:
                self.text.append(label)
                if self._diagram_tags:
                    self.diagram.append(label)

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            if tag in {"script", "style", "noscript"}:
                self._skip_depth -= 1
            return
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self._heading_depth:
            self._heading_depth -= 1
        for index in range(len(self._diagram_tags) - 1, -1, -1):
            if self._diagram_tags[index] == tag:
                del self._diagram_tags[index]
                break

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = _normalize(data)
        if not value:
            return
        self.text.append(value)
        if self._title_depth:
            self.title = _join_text((self.title, value))
        if self._heading_depth and (not self.headings or self.headings[-1] != value):
            self.headings.append(value)
        if self._diagram_tags:
            self.diagram.append(value)


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _join_text(values: tuple[str, ...] | list[str]) -> str:
    return " ".join(value for value in values if value).strip()


def extract_html_reference(
    source: str | Path,
    *,
    max_chars: int = 12000,
) -> dict[str, Any]:
    """Read visible HTML text and diagram labels without running scripts."""
    path = Path(source)
    parser = _ReferenceParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    text = _join_text(parser.text)
    diagram = _join_text(parser.diagram)
    limit = max(1, int(max_chars))
    return {
        "schema": "html-reference/v1",
        "title": parser.title[:240],
        "headings": list(dict.fromkeys(parser.headings))[:100],
        "diagram_excerpt": diagram[:min(limit, 6000)],
        "text_excerpt": text[:limit],
        "truncated": len(text) > limit or len(diagram) > min(limit, 6000),
    }


__all__ = ["extract_html_reference"]
