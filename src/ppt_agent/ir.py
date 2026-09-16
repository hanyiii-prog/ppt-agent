from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
import json

from .contracts import IR_SCHEMA_VERSION, SUPPORTED_IR_VERSIONS


@dataclass(frozen=True)
class Provenance:
    source_id: str
    locator: str | None = None
    quote: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Provenance":
        return cls(
            source_id=str(data.get("source_id", "")),
            locator=data.get("locator"),
            quote=data.get("quote"),
        )


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Component":
        return cls(
            type=str(data.get("type") or "shape"),
            id=data.get("id"),
            x=data.get("x"),
            y=data.get("y"),
            w=data.get("w"),
            h=data.get("h"),
            text=data.get("text"),
            data=data.get("data"),
            style=dict(data.get("style") or {}),
            provenance=[
                Provenance.from_dict(item)
                for item in (data.get("provenance") or [])
                if isinstance(item, dict)
            ],
        )


@dataclass
class Slide:
    id: str
    purpose: str
    claim: str | None = None
    layout: str | None = None
    components: list[Component] = field(default_factory=list)
    speaker_notes: str | None = None
    data: Any = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Slide":
        return cls(
            id=str(data.get("id") or ""),
            purpose=str(data.get("purpose") or "content"),
            claim=data.get("claim"),
            layout=data.get("layout"),
            components=[
                Component.from_dict(item)
                for item in (data.get("components") or [])
                if isinstance(item, dict)
            ],
            speaker_notes=data.get("speaker_notes"),
            data=data.get("data"),
        )


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
        # `ir_version` is the stable contract stamp; `version` stays as the
        # dialect marker for backwards compatibility with V0.x consumers.
        data["ir_version"] = IR_SCHEMA_VERSION
        data["version"] = self.version or IR_SCHEMA_VERSION
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Presentation":
        meta = data.get("metadata") or {}
        version = str(
            data.get("version")
            or data.get("ir_version")
            or meta.get("ir_version")
            or IR_SCHEMA_VERSION
        )
        return cls(
            version=version,
            title=str(meta.get("title") or data.get("title") or "Untitled Presentation"),
            slides=[
                Slide.from_dict(item)
                for item in (data.get("slides") or [])
                if isinstance(item, dict)
            ],
            audience=meta.get("audience") or data.get("audience"),
            objective=meta.get("objective") or data.get("objective"),
            theme=dict(data.get("theme") or {}),
            sources=list(data.get("sources") or []),
        )


def validate_presentation(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("version", "metadata", "slides"):
        if key not in data:
            errors.append(f"missing required field: {key}")
    version = data.get("version") or data.get("ir_version")
    if version is not None and str(version) not in SUPPORTED_IR_VERSIONS:
        errors.append(
            f"unsupported IR version {version!r}; supported: {', '.join(SUPPORTED_IR_VERSIONS)}"
        )
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
