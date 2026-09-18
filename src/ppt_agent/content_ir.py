"""Content IR (schema ``content-ir/v0.1``) -- the intermediate for *content*.

Why this exists
---------------
Until now the only parse target was the Presentation IR (slides and
components). The V2.1 pipeline needs a step *before* slides exist: whatever
the user brought -- Markdown, Word, an old deck -- becomes a format-neutral
document of typed blocks; the analyzer, page-count engine, narrative engine
and presentation planner all read *this*, not the source format.

Block types
-----------
``heading`` (level 1-6) / ``paragraph`` / ``bullets`` / ``ordered`` /
``table`` (headers + rows) / ``quote``.

The schema is stamped ``schema: "content-ir/v0.1"`` and checked by
``contracts.check_content_ir_version``. Parsers produce it, the analyzer
enriches it (``analysis`` per block, ``analyzer`` in metadata), planners
consume it. No LLM anywhere in this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
import json

SCHEMA = "content-ir/v0.1"

BLOCK_TYPES: tuple[str, ...] = (
    "heading", "paragraph", "bullets", "ordered", "table", "quote",
)


@dataclass
class ContentBlock:
    """One typed content unit. ``analysis`` is added by content_analyzer."""

    type: str
    id: str
    text: str | None = None
    level: int | None = None            # heading level (1-6)
    items: list[str] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    source: str | None = None           # parser hint: "markdown" / "docx" / "pptx"
    analysis: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContentBlock":
        return cls(
            type=str(data.get("type") or "paragraph"),
            id=str(data.get("id") or ""),
            text=data.get("text"),
            level=data.get("level"),
            items=[str(item) for item in (data.get("items") or [])],
            headers=[str(item) for item in (data.get("headers") or [])],
            rows=[
                [str(cell) for cell in row]
                for row in (data.get("rows") or [])
                if isinstance(row, list)
            ],
            source=data.get("source"),
            analysis=dict(data.get("analysis") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def char_volume(self) -> int:
        """Rough content volume: the number the page-count engine reasons on."""
        if self.type == "heading":
            return len(self.text or "")
        if self.type in ("bullets", "ordered"):
            return sum(len(item) for item in self.items)
        if self.type == "table":
            cells = len(self.headers) + sum(len(row) for row in self.rows)
            return cells * 12  # a table cell is worth ~12 CJK chars of layout budget
        return len(self.text or "")


@dataclass
class ContentDocument:
    """Format-neutral content document (the Content IR payload)."""

    schema: str = SCHEMA
    source: str | None = None
    format: str | None = None           # markdown / docx / pptx
    title: str | None = None
    blocks: list[ContentBlock] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContentDocument":
        return cls(
            schema=str(data.get("schema") or SCHEMA),
            source=data.get("source"),
            format=data.get("format"),
            title=data.get("title"),
            blocks=[
                ContentBlock.from_dict(item)
                for item in (data.get("blocks") or [])
                if isinstance(item, dict)
            ],
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "ContentDocument":
        return cls.from_dict(json.loads(text))

    def headings(self) -> list[ContentBlock]:
        return [block for block in self.blocks if block.type == "heading"]

    def sections(self) -> list[tuple[ContentBlock, list[ContentBlock]]]:
        """Split blocks into (heading, children) pairs at level <= 2."""
        result: list[tuple[ContentBlock, list[ContentBlock]]] = []
        current: ContentBlock | None = None
        children: list[ContentBlock] = []
        for block in self.blocks:
            if block.type == "heading" and (block.level or 1) <= 2:
                if current is not None:
                    result.append((current, children))
                current, children = block, []
            elif current is not None:
                children.append(block)
        if current is not None:
            result.append((current, children))
        return result
