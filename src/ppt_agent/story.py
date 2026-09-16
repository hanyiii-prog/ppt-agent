from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .contracts import IR_SCHEMA_VERSION
from .ir import Component, Presentation, Provenance, Slide

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_BULLET = re.compile(r"^[-*]\s+(.+)$")
_NUMBERED = re.compile(r"^\d+[.)]\s+(.+)$")

_COVER_KEYS = ("封面", "cover", "标题页", "title")
_AGENDA_KEYS = ("目录", "agenda", "outline", "contents")
_CLOSING_KEYS = ("总结", "结论", "closing", "summary", "thanks", "谢谢", "结尾")


def _infer_purpose(heading: str) -> str:
    text = (heading or "").lower()
    if any(key in text for key in _COVER_KEYS):
        return "cover"
    if any(key in text for key in _AGENDA_KEYS):
        return "agenda"
    if any(key in text for key in _CLOSING_KEYS):
        return "closing"
    return "content"


@dataclass
class StorySlide:
    purpose: str
    claim: str | None = None
    points: list[str] = field(default_factory=list)


@dataclass
class Story:
    """A structured narrative outline produced before any slide is drawn."""

    title: str
    audience: str | None = None
    objective: str | None = None
    slides: list[StorySlide] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _point_of(line: str) -> str | None:
    bullet = _BULLET.match(line)
    if bullet:
        return bullet.group(1).strip()
    numbered = _NUMBERED.match(line)
    if numbered:
        return numbered.group(1).strip()
    return line.strip() or None


def architect_story(
    markdown: str,
    *,
    title: str | None = None,
    audience: str | None = None,
    objective: str | None = None,
) -> Story:
    """Turn raw Markdown into a structured Story (claim + supporting points per slide)."""
    story_title = title
    slides: list[StorySlide] = []
    current: StorySlide | None = None

    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = _HEADING.match(line)
        if heading and len(heading.group(1)) == 1:
            story_title = story_title or heading.group(2)
            continue
        if heading and len(heading.group(1)) == 2:
            current = StorySlide(purpose=_infer_purpose(heading.group(2)), claim=heading.group(2))
            slides.append(current)
            continue
        point = _point_of(line)
        if point is None:
            continue
        if current is None:
            current = StorySlide(purpose="cover", claim=story_title or "Untitled")
            slides.append(current)
        current.points.append(point)

    if not slides and story_title:
        slides.append(StorySlide(purpose="cover", claim=story_title))

    return Story(
        title=story_title or "Untitled Presentation",
        audience=audience,
        objective=objective,
        slides=slides,
    )


def story_to_ir(story: Story) -> Presentation:
    """Materialize a Story outline into Universal IR using deterministic flow layout."""
    slides: list[Slide] = []
    for index, entry in enumerate(story.slides, 1):
        components: list[Component] = []
        provenance = [Provenance(source_id="story-architect", locator=f"slide:{index}")]
        if entry.claim:
            components.append(
                Component(type="title", id=f"slide-{index:02d}-title", text=entry.claim, provenance=list(provenance))
            )
        for point_index, point in enumerate(entry.points, 1):
            components.append(
                Component(
                    type="text",
                    id=f"slide-{index:02d}-p-{point_index:02d}",
                    text=point,
                    provenance=list(provenance),
                )
            )
        slides.append(
            Slide(id=f"slide-{index:02d}", purpose=entry.purpose, claim=entry.claim, components=components)
        )
    return Presentation(
        version=IR_SCHEMA_VERSION,
        title=story.title,
        slides=slides,
        audience=story.audience,
        objective=story.objective,
        sources=[{"id": "story-architect", "type": "story"}],
    )


def architect_markdown_to_ir(markdown: str, **kwargs: Any) -> Presentation:
    return story_to_ir(architect_story(markdown, **kwargs))
