from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Provenance:
    source_id: str
    locator: str | None = None
    quote: str | None = None


@dataclass
class Component:
    type: str
    id: str | None = None
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    text: str | None = None
    data: Any = None
    style: dict[str, Any] = field(default_factory=dict)
    provenance: list[Provenance] = field(default_factory=list)


@dataclass
class Slide:
    id: str
    purpose: str
    claim: str | None = None
    layout: str | None = None
    components: list[Component] = field(default_factory=list)
    speaker_notes: str | None = None


@dataclass
class Presentation:
    version: str
    title: str
    slides: list[Slide] = field(default_factory=list)
    audience: str | None = None
    objective: str | None = None
    theme: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def convert(value: Any) -> Any:
            if hasattr(value, "__dataclass_fields__"):
                return {k: convert(v) for k, v in value.__dict__.items()}
            if isinstance(value, list):
                return [convert(v) for v in value]
            if isinstance(value, dict):
                return {k: convert(v) for k, v in value.items()}
            return value

        return {
            "version": self.version,
            "metadata": {
                "title": self.title,
                "audience": self.audience,
                "objective": self.objective,
            },
            "theme": convert(self.theme),
            "sources": convert(self.sources),
            "slides": convert(self.slides),
        }
