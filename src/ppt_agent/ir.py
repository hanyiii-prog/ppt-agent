from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
import json


@dataclass(frozen=True)
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
    data: Any = None


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
        data = asdict(self)
        data["metadata"] = {
            "title": self.title,
            "audience": self.audience,
            "objective": self.objective,
        }
        data.pop("title", None)
        data.pop("audience", None)
        data.pop("objective", None)
        return data

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def validate_presentation(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("version", "metadata", "slides"):
        if key not in data:
            errors.append(f"missing required field: {key}")
    if not isinstance(data.get("slides"), list):
        errors.append("slides must be an array")
        return errors
    if not isinstance(data.get("metadata"), dict):
        errors.append("metadata must be an object")
    for i, slide in enumerate(data["slides"]):
        if not isinstance(slide, dict):
            errors.append(f"slides[{i}] must be an object")
            continue
        for key in ("id", "purpose"):
            if not slide.get(key):
                errors.append(f"slides[{i}] missing {key}")
        components = slide.get("components", [])
        if not isinstance(components, list):
            errors.append(f"slides[{i}].components must be an array")
            continue
        for j, component in enumerate(components):
            if not isinstance(component, dict) or not component.get("type"):
                errors.append(f"slides[{i}].components[{j}] missing type")
    return errors
