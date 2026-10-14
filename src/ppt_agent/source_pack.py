from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Sequence

from .content_ir import ContentBlock, ContentDocument
from .parsers import parse_auto

SCHEMA = "source-pack/v1"


@dataclass
class SourceRef:
    id: str
    path: str
    format: str
    priority: str
    content_hash: str
    block_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourcePack:
    schema: str
    title: str | None
    sources: list[SourceRef]
    blocks: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_document(cls, document: ContentDocument, source_path: Path) -> "SourcePack":
        raw = source_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        block_ids = [block.id for block in document.blocks]
        ref = SourceRef(
            id="source-001",
            path=str(source_path),
            format=str(document.format or source_path.suffix.lstrip(".")),
            priority="primary",
            content_hash=digest,
            block_ids=block_ids,
        )
        return cls(
            schema=SCHEMA,
            title=document.title,
            sources=[ref],
            blocks=[_block_to_dict(block, ref.id) for block in document.blocks],
            metadata={"parser": document.metadata, "warnings": []},
        )

    @classmethod
    def from_documents(cls, documents: list[ContentDocument], source_paths: list[Path]) -> "SourcePack":
        sources: list[SourceRef] = []
        blocks: list[dict[str, Any]] = []
        warnings: list[str] = []
        for index, (document, source_path) in enumerate(zip(documents, source_paths), 1):
            raw = source_path.read_bytes()
            ref = SourceRef(
                id=f"source-{index:03d}",
                path=str(source_path),
                format=str(document.format or source_path.suffix.lstrip(".")),
                priority="primary" if index == 1 else "supporting",
                content_hash=hashlib.sha256(raw).hexdigest(),
                block_ids=[],
            )
            block_dicts: list[dict[str, Any]] = []
            for block in document.blocks:
                item = _block_to_dict(block, ref.id, index)
                block_dicts.append(item)
                ref.block_ids.append(item["id"])
                blocks.append(item)
            sources.append(ref)
            warnings.extend(document.metadata.get("warnings") or [])
        return cls(
            schema=SCHEMA,
            title=documents[0].title if documents else None,
            sources=sources,
            blocks=blocks,
            metadata={"parser": "multi-source", "warnings": warnings},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_source_pack(
    source: str | Path | Sequence[str | Path],
    *,
    source_priority: Sequence[str] | None = None,
) -> tuple[ContentDocument, SourcePack]:
    """Parse one or more supported files into a versioned source pack."""
    if isinstance(source, (str, Path)):
        paths = [Path(source)]
    else:
        paths = [Path(item) for item in source]
    if not paths:
        raise ValueError("source files are required")
    documents = [_parse_supported(path) for path in paths]
    pack = SourcePack.from_documents(documents, paths)
    _apply_source_priority(pack, source_priority or [])
    return documents[0], pack


def _parse_supported(path: Path) -> ContentDocument:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return _parse_html(path)
    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return _parse_image(path)
    return parse_auto(path)


def _parse_html(path: Path) -> ContentDocument:
    parser = _StructuredHtmlParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return ContentDocument(
        source=str(path),
        format="html",
        title=parser.title,
        blocks=parser.blocks,
        metadata={"parser": "html/stdlib", "warnings": []},
    )


def _parse_pdf(path: Path) -> ContentDocument:
    from .pdf_reference import extract_pdf_reference

    reference = extract_pdf_reference(path)
    blocks: list[ContentBlock] = []
    counter = 1
    for page in reference.get("pages") or []:
        text = str(page.get("text") or "").strip()
        if not text:
            continue
        blocks.append(ContentBlock(
            type="paragraph", id=f"p-{counter:04d}", text=text, source="pdf",
        ))
        counter += 1
    return ContentDocument(
        source=str(path), format="pdf",
        title=path.stem, blocks=blocks,
        metadata={
            "parser": "pdf/pymupdf",
            "warnings": [] if reference.get("methods") else ["pdf text extraction produced no content"],
        },
    )


def _parse_image(path: Path) -> ContentDocument:
    return ContentDocument(
        source=str(path), format=path.suffix.lstrip("."), title=path.stem,
        blocks=[ContentBlock(
            type="paragraph", id="p-0001",
            text="[image source present; visual content requires a vision-capable model]",
            source="image",
        )],
        metadata={"parser": "image/reference-only", "warnings": ["image text requires OCR or a vision model"]},
    )


def _block_to_dict(
    block: ContentBlock,
    source_id: str,
    source_index: int = 1,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": f"s{source_index:03d}-{block.id}",
        "source_id": source_id,
        "type": block.type,
        "facts": [],
        "location": f"block:{block.id}",
    }
    if block.text is not None:
        value["text"] = block.text
    if block.level is not None:
        value["level"] = block.level
    if block.items:
        value["items"] = list(block.items)
    if block.headers:
        value["headers"] = list(block.headers)
    if block.rows:
        value["rows"] = [list(row) for row in block.rows]
    if block.source:
        value["source"] = block.source
    return value


class _StructuredHtmlParser(HTMLParser):
    """Extract visible document structure without scripts, styles or libraries."""

    _HEADINGS = {f"h{index}": index for index in range(1, 7)}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.blocks: list[ContentBlock] = []
        self._counter = 0
        self._capture: str | None = None
        self._heading_level = 2
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "title":
            self._capture = "title"
        elif tag in self._HEADINGS:
            self._start_block("heading", self._HEADINGS[tag])
        elif tag in {"p", "li", "blockquote"}:
            self._start_block("paragraph")

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        text = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
        if self._capture == "title" and tag == "title":
            self.title = text or None
        elif self._capture in {"heading", "paragraph"} and text:
            self._counter += 1
            if self._capture == "heading":
                self.blocks.append(ContentBlock(
                    type="heading", id=f"h-{self._counter:04d}",
                    text=text, level=self._heading_level, source="html",
                ))
            else:
                self.blocks.append(ContentBlock(
                    type="paragraph", id=f"p-{self._counter:04d}",
                    text=text, source="html",
                ))
        if tag == "title" or self._capture in {"heading", "paragraph"}:
            self._capture = None
            self._parts = []

    def _start_block(self, kind: str, level: int = 2) -> None:
        self._capture = kind
        self._heading_level = level
        self._parts = []


def _apply_source_priority(pack: SourcePack, source_priority: Sequence[str]) -> None:
    """Let the user mark a primary source by id, path or file name."""
    priorities = [str(item) for item in source_priority if str(item).strip()]
    if not priorities:
        return
    selected: str | None = None
    for ref in pack.sources:
        candidates = {ref.id, ref.path, Path(ref.path).name}
        if any(item in candidates for item in priorities):
            selected = ref.id
            break
    for ref in pack.sources:
        ref.priority = "primary" if ref.id == selected else "supporting"


__all__ = ["SourcePack", "SourceRef", "SCHEMA", "build_source_pack"]
