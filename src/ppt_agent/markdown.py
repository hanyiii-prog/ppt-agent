from __future__ import annotations

import re

from .contracts import IR_SCHEMA_VERSION
from .ir import Component, Presentation, Provenance, Slide

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_NUMBERED = re.compile(r"^\d+[.)]\s+(.+)$")


def parse_markdown(text: str, *, source_id: str = "markdown") -> Presentation:
    """Parse a deliberately conservative Markdown subset into Presentation IR.

    H1 is the deck title. H2 starts a slide. Body lines become paragraph/bullet
    components and retain their source line as provenance.
    """
    title = "Untitled Presentation"
    slides: list[Slide] = []
    current: Slide | None = None
    body: list[tuple[int, str]] = []

    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        match = _HEADING.match(line)
        if match and len(match.group(1)) == 1:
            title = match.group(2)
        elif match and len(match.group(1)) == 2:
            if current is not None:
                _finalize(current, body, source_id)
                slides.append(current)
            current = Slide(
                id=f"slide-{len(slides) + 1:02d}",
                purpose=match.group(2),
                claim=match.group(2),
            )
            body = []
        elif current is not None:
            body.append((line_no, line))

    if current is not None:
        _finalize(current, body, source_id)
        slides.append(current)

    return Presentation(
        version=IR_SCHEMA_VERSION,
        title=title,
        slides=slides,
        sources=[{"id": source_id, "type": "markdown"}],
    )


def _finalize(slide: Slide, body: list[tuple[int, str]], source_id: str) -> None:
    for index, (line_no, line) in enumerate(body, 1):
        text = line
        kind = "paragraph"
        if line.startswith(("- ", "* ")):
            kind = "text"
            text = line[2:].strip()
        else:
            numbered = _NUMBERED.match(line)
            if numbered:
                kind = "text"
                text = numbered.group(1)
        slide.components.append(
            Component(
                type=kind,
                id=f"{slide.id}-c-{index:02d}",
                text=text,
                provenance=[Provenance(source_id, f"L{line_no}", text)],
            )
        )
