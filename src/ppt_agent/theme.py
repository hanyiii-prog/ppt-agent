"""Visual theme tokens for the design layer.

A theme is a complete visual identity: palette, type scale and type rhythm.
The design layer reads these tokens to compose slides into positioned,
styled primitives, so changing a theme restyles the whole deck without
touching layout code.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping


@dataclass(frozen=True)
class Theme:
    """Palette + type scale used by every designed slide."""

    name: str = "clinical-blue"

    # --- palette (uppercase 6-digit hex, no leading '#') ---
    primary: str = "11506E"
    primary_deep: str = "0A3A52"
    primary_soft: str = "E9F0F5"
    accent: str = "1B9AAA"
    accent_soft: str = "D6EBEF"
    warm: str = "C8861B"
    text: str = "1F2933"
    text_muted: str = "64748B"
    text_inverse: str = "FFFFFF"
    line: str = "D9E2E8"
    surface: str = "FFFFFF"

    # --- typography ---
    font_title: str = "Microsoft YaHei"
    font_body: str = "Microsoft YaHei"

    # --- type scale, points ---
    cover_title_pt: float = 40.0
    cover_sub_pt: float = 16.0
    cover_meta_pt: float = 12.0
    section_title_pt: float = 30.0
    slide_title_pt: float = 26.0
    body_pt: float = 16.0
    agenda_no_pt: float = 17.0
    closing_title_pt: float = 32.0
    closing_body_pt: float = 14.0
    footer_pt: float = 11.0

    # --- layout rhythm (inches) ---
    margin_x: float = 0.9
    title_top: float = 0.52
    body_top: float = 1.72
    footer_rule_y: float = 6.78
    footer_text_y: float = 6.90
    body_indent: float = 0.40
    bullet_gap: float = 0.22

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def with_overrides(self, values: Mapping[str, Any] | None) -> "Theme":
        """Return a copy with recognised token overrides applied."""
        if not values:
            return self
        known = {key: value for key, value in values.items() if key in self.to_dict()}
        if not known:
            return self
        for key, value in list(known.items()):
            current = getattr(self, key)
            if isinstance(current, float) and isinstance(value, (int, float)):
                known[key] = float(value)
        return replace(self, **known)


DEFAULT_THEME = Theme()

# Ready-made palettes so a deck can be restyled with one word.
THEMES: dict[str, Theme] = {
    "clinical-blue": DEFAULT_THEME,
    "graphite": Theme(
        name="graphite",
        primary="33404A",
        primary_deep="1C252C",
        primary_soft="EEF1F3",
        accent="C8861B",
        accent_soft="F6EAD6",
        line="DCE2E6",
    ),
    "teal-green": Theme(
        name="teal-green",
        primary="136F63",
        primary_deep="0B4A42",
        primary_soft="E6F2F0",
        accent="D98A1F",
        accent_soft="FAEEDA",
        line="D6E4E1",
    ),
}


def resolve_theme(name: str | Theme | None = None) -> Theme:
    if isinstance(name, Theme):
        return name
    if isinstance(name, str) and name in THEMES:
        return THEMES[name]
    return DEFAULT_THEME
