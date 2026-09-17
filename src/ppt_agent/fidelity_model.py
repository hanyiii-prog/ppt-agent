"""Canonical Fidelity Model: one data model for the whole fidelity engine.

``build_deck_fidelity`` turns a real PPTX into a ``DeckFidelity`` tree whose
every element knows where it came from (master / layout / slide), where it
sits in the global render order, what its resolved style is, and which raw
OOXML evidence backs it. Downstream stages (matching, diff, repair, gate)
consume this model instead of reinterpreting package internals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .fidelity import extract_fidelity_dna

SOURCES = ("master", "layout", "slide")


@dataclass
class ElementFidelity:
    """One renderable element, resolved across the inheritance chain."""

    element_id: str | None
    name: str | None
    kind: str
    source: str
    parent: str | None
    render_order: int
    source_z: int
    geometry: dict[str, Any] | None
    fill: dict[str, Any] | None = None
    line: dict[str, Any] | None = None
    effects: list[dict[str, Any]] | None = None
    typography: dict[str, Any] | None = None
    text: str | None = None
    media: dict[str, Any] | None = None
    crop: dict[str, Any] | None = None
    custom_geometry: dict[str, Any] | None = None
    placeholder: dict[str, Any] | None = None
    table: dict[str, Any] | None = None
    connector: dict[str, Any] | None = None
    preset_geometry: dict[str, Any] | None = None
    children: list["ElementFidelity"] = field(default_factory=list)
    raw_ooxml_evidence: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, record: dict[str, Any], source: str) -> "ElementFidelity":
        media = record.get("media") or None
        crop = (media or {}).get("crop") or (record.get("media") or {}).get("crop")
        return cls(
            element_id=record.get("shape_id"),
            name=record.get("name"),
            kind=str(record.get("kind", "sp")),
            source=source,
            parent=record.get("parent_id"),
            render_order=int(record.get("global_render_order", record.get("z_index", 0))),
            source_z=int(record.get("z_index", 0)),
            geometry=record.get("geometry_emu"),
            fill=record.get("fill"),
            line=record.get("line"),
            effects=record.get("effects"),
            typography=record.get("typography"),
            text=record.get("text"),
            media=media,
            crop=crop,
            custom_geometry=record.get("custom_geometry"),
            placeholder=record.get("placeholder"),
            table=record.get("table"),
            connector=record.get("connector"),
            preset_geometry=record.get("preset_geometry"),
            children=[cls.from_record(child, source) for child in record.get("children", [])],
            raw_ooxml_evidence={
                key: record[key]
                for key in ("raw_xml", "spPr_xml", "text_body_xml", "custom_geometry_xml")
                if record.get(key) is not None
            },
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            key: value
            for key, value in self.__dict__.items()
            if key != "children" and value is not None
        }
        payload["children"] = [child.to_dict() for child in self.children]
        return payload


@dataclass
class SlideFidelity:
    """One slide: page kind, resolved background and globally ordered layers."""

    index: int
    page_kind: str
    page_size: dict[str, int]
    background: dict[str, Any] | None
    toc: dict[str, Any] | None
    rendered_layers: list[ElementFidelity]
    assets: dict[str, Any]
    layout_name: str | None = None
    placeholder_resolutions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def inherited_layers(self) -> list[ElementFidelity]:
        return [layer for layer in self.rendered_layers if layer.source in ("master", "layout")]

    @property
    def local_layers(self) -> list[ElementFidelity]:
        return [layer for layer in self.rendered_layers if layer.source == "slide"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "page_kind": self.page_kind,
            "page_size": self.page_size,
            "background": self.background,
            "layout_name": self.layout_name,
            "toc": self.toc,
            "rendered_layers": [layer.to_dict() for layer in self.rendered_layers],
            "inherited_layers": [layer.to_dict() for layer in self.inherited_layers],
            "local_layers": [layer.to_dict() for layer in self.local_layers],
            "placeholder_resolutions": self.placeholder_resolutions,
            "assets": self.assets,
        }


@dataclass
class DeckFidelity:
    """Deck-level canonical model: presentation, theme, masters, layouts, slides."""

    source: str
    schema_version: str
    presentation: dict[str, Any]
    theme: dict[str, Any]
    slides: list[SlideFidelity]
    assets: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "schema": self.schema_version,
            "presentation": self.presentation,
            "theme": self.theme,
            "slides": [slide.to_dict() for slide in self.slides],
            "assets": self.assets,
        }


def build_slide_fidelity(dna: dict[str, Any]) -> SlideFidelity:
    """Flatten one extracted slide DNA into globally ordered layers."""
    layers: list[ElementFidelity] = []
    for source in SOURCES:
        container = dna.get(source) or {}
        for record in container.get("shapes", []):
            layers.append(ElementFidelity.from_record(record, source))
    layers.sort(key=lambda layer: layer.render_order)

    background = (dna.get("slide") or {}).get("background")
    if background is None:
        background = next(
            (entry for entry in (dna.get("slide") or {}).get("background_resolved", []) if entry.get("source") in ("layout", "master")),
            None,
        )
    return SlideFidelity(
        index=int(dna.get("slide_index", 1)),
        page_kind=str(dna.get("page_kind", "content")),
        page_size=dna.get("presentation", {}).get("slide_size_emu", {}),
        background=background,
        toc=dna.get("toc"),
        rendered_layers=layers,
        assets=dna.get("assets", {}),
        layout_name=(dna.get("layout") or {}).get("name"),
        placeholder_resolutions=dna.get("placeholder_resolutions", []),
    )


def build_deck_fidelity(path: str | Path, *, slide_indexes: list[int] | None = None) -> DeckFidelity:
    """Extract every slide of a real PPTX into the canonical model."""
    source = Path(path)
    first = extract_fidelity_dna(source, slide_index=1)
    count = first["presentation"]["slide_count"]
    indexes = slide_indexes or list(range(1, count + 1))
    slides = [
        build_slide_fidelity(extract_fidelity_dna(source, slide_index=index) if index != 1 else first)
        for index in indexes
    ]
    return DeckFidelity(
        source=str(source),
        schema_version=str(first.get("schema", "")),
        presentation=dict(first.get("presentation", {})),
        theme=dict(first.get("theme", {})),
        slides=slides,
        assets=first.get("assets", {}),
    )
