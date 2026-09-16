"""Visual theme tokens for the design layer.

A theme is a complete visual identity: palette, type scale and type rhythm.
The design layer reads these tokens to compose slides into positioned,
styled primitives, so changing a theme restyles the whole deck without
touching layout code.
"""
from __future__ import annotations

import colorsys
from collections import Counter
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping, Sequence


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


# --------------------------------------------------------------------------
# Template DNA -> Theme
# --------------------------------------------------------------------------

_WHITE = (255, 255, 255)
_BLACK = (0, 0, 0)


def _rgb_tuple(value: Any) -> tuple[int, int, int] | None:
    text = str(value or "").strip().lstrip("#").upper()
    if len(text) == 6 and all(char in "0123456789ABCDEF" for char in text):
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    return None


def _hex_code(rgb: tuple[int, int, int]) -> str:
    return "%02X%02X%02X" % rgb


def _mix(first: tuple[int, int, int], second: tuple[int, int, int], weight: float) -> tuple[int, int, int]:
    """Blend ``weight`` of ``second`` into ``first``."""
    ratio = max(0.0, min(1.0, float(weight)))
    return tuple(round(a * (1 - ratio) + b * ratio) for a, b in zip(first, second))


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    channels = []
    for value in rgb:
        channel = value / 255.0
        channels.append(channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _saturation(rgb: tuple[int, int, int]) -> float:
    high, low = max(rgb), min(rgb)
    return 0.0 if high == 0 else (high - low) / high


def _hue(rgb: tuple[int, int, int]) -> float:
    red, green, blue = (value / 255.0 for value in rgb)
    high, low = max(red, green, blue), min(red, green, blue)
    span = high - low
    if span == 0:
        return 0.0
    if high == red:
        sector = ((green - blue) / span) % 6
    elif high == green:
        sector = (blue - red) / span + 2
    else:
        sector = (red - green) / span + 4
    return sector * 60.0


def _hue_distance(first: float, second: float) -> float:
    delta = abs(first - second) % 360.0
    return min(delta, 360.0 - delta)


def _rotate_hue(rgb: tuple[int, int, int], degrees: float) -> tuple[int, int, int]:
    red, green, blue = (value / 255.0 for value in rgb)
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    red2, green2, blue2 = colorsys.hls_to_rgb((hue + degrees / 360.0) % 1.0, lightness, saturation)
    return round(red2 * 255), round(green2 * 255), round(blue2 * 255)


def _clamp(value: Any, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _neutral_from(rgb: tuple[int, int, int], *, lightness: float = 0.16, saturation: float = 0.16) -> tuple[int, int, int]:
    """A near-neutral ink that keeps a trace of the source hue."""
    hue, _current, _saturation = colorsys.rgb_to_hls(*(value / 255.0 for value in rgb))
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return round(red * 255), round(green * 255), round(blue * 255)


def _pick_accent(
    primary: tuple[int, int, int],
    mids: Sequence[tuple[tuple[int, int, int], int]],
    scheme: Mapping[str, Any],
) -> tuple[int, int, int]:
    """Pick the colour that reads as a distinct accent against ``primary``."""
    primary_hue = _hue(primary)
    distant = [
        (rgb, weight)
        for rgb, weight in mids
        if rgb != primary and _hue_distance(_hue(rgb), primary_hue) >= 45.0
    ]
    if distant:
        return max(distant, key=lambda item: (item[1], _saturation(item[0])))[0]
    for slot in ("accent2", "accent3"):
        rgb = _rgb_tuple(scheme.get(slot, ""))
        if rgb is not None and _saturation(rgb) >= 0.18:
            return rgb
    # Nothing distinct survived: rotate the hue so the deck still has contrast.
    return _rotate_hue(primary, 150.0)


def theme_from_dna(dna: Any, *, name: str = "template") -> Theme:
    """Derive a theme from Template DNA.

    Colours and fonts are read from the reference deck, so a deck built with
    ``--template`` inherits that deck's visual identity instead of a built-in
    preset. Layout rhythm keeps the defaults: DNA carries per-shape geometry
    rather than a versioned rhythm, and guessing one would be less faithful
    than not guessing at all.
    """
    if not isinstance(dna, dict):
        return replace(DEFAULT_THEME, name=name)

    stats = dna.get("global_style_statistics")
    stats = stats if isinstance(stats, dict) else {}
    block = dna.get("theme")
    scheme = block.get("colors") if isinstance(block, dict) else {}
    scheme = scheme if isinstance(scheme, dict) else {}

    # --- colour candidates, weighted by how often the deck actually uses them
    weights: Counter[tuple[int, int, int]] = Counter()
    for entry in stats.get("fills_rgb") or []:
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            rgb = _rgb_tuple(entry[0])
            if rgb is None:
                continue
            try:
                weights[rgb] += max(1, int(entry[1]))
            except (TypeError, ValueError):
                weights[rgb] += 1
    # Scheme slots matter when the deck paints with theme colours instead of literals.
    for slot in ("accent1", "accent2", "accent3", "accent4", "dk1", "dk2"):
        rgb = _rgb_tuple(scheme.get(slot, ""))
        if rgb is not None:
            weights[rgb] += 2

    inks = [(rgb, weight) for rgb, weight in weights.items() if _relative_luminance(rgb) < 0.30]
    mids = [
        (rgb, weight)
        for rgb, weight in weights.items()
        if _saturation(rgb) >= 0.18 and 0.12 <= _relative_luminance(rgb) <= 0.80
    ]

    if inks:
        primary = max(inks, key=lambda item: (item[1], -_relative_luminance(item[0])))[0]
    else:
        primary = _rgb_tuple(scheme.get("accent1", "")) or _rgb_tuple(DEFAULT_THEME.primary) or _BLACK
    accent = _pick_accent(primary, mids, scheme)

    # Body ink: use the template's own dark scheme slot only when it sits in the
    # same hue family as the brand colour. A stock `dk2` left over from the Office
    # palette (often a blue) is a leftover, not a design decision, so it is ignored
    # in favour of an ink derived from the primary colour.
    text = _rgb_tuple(scheme.get("dk1", ""))
    if text is None or _relative_luminance(text) > 0.30:
        candidate = _rgb_tuple(scheme.get("dk2", ""))
        if (
            candidate is not None
            and _relative_luminance(candidate) <= 0.30
            and _hue_distance(_hue(candidate), _hue(primary)) <= 60.0
        ):
            text = candidate
        else:
            text = _neutral_from(primary)

    deep = _mix(_BLACK, primary, 0.62)
    soft = _mix(_WHITE, primary, 0.08)
    accent_soft = _mix(_WHITE, accent, 0.14)
    line = _mix(_WHITE, primary, 0.18)
    muted = _mix(_WHITE, text, 0.45)
    inverse = _WHITE if _relative_luminance(deep) < 0.45 else _BLACK

    # --- typography: the font the deck leans on most, in order of frequency
    fonts: list[str] = []
    for entry in stats.get("fonts") or []:
        if isinstance(entry, (list, tuple)) and entry:
            label = str(entry[0] or "").strip()
            if label and not label.startswith("+") and label not in fonts:
                fonts.append(label)
    font_title = fonts[0] if fonts else DEFAULT_THEME.font_title
    font_body = fonts[0] if fonts else DEFAULT_THEME.font_body

    ladder: Counter[float] = Counter()
    for entry in stats.get("font_sizes_pt") or []:
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            try:
                size = round(float(entry[0]), 1)
                count = int(entry[1])
            except (TypeError, ValueError):
                continue
            if 8.0 <= size <= 72.0:
                ladder[size] += max(1, count)

    ranked = sorted(ladder, reverse=True)
    cover = _clamp(ranked[0] if ranked else DEFAULT_THEME.cover_title_pt, 26.0, 54.0)
    section = min(_clamp(ranked[1] if len(ranked) > 1 else cover * 0.78, 20.0, 38.0), cover - 2.0)
    heading = min(_clamp(ranked[2] if len(ranked) > 2 else section * 0.88, 17.0, 30.0), section - 2.0)
    pool = [size for size in ladder if size <= heading - 1.0]
    body_source = max(pool, key=lambda size: (ladder[size], size)) if pool else DEFAULT_THEME.body_pt
    body = _clamp(min(body_source, heading - 2.0), 11.0, 22.0)
    footer = _clamp(min(ladder) if ladder else DEFAULT_THEME.footer_pt, 8.0, 13.0)

    return Theme(
        name=name,
        primary=_hex_code(primary),
        primary_deep=_hex_code(deep),
        primary_soft=_hex_code(soft),
        accent=_hex_code(accent),
        accent_soft=_hex_code(accent_soft),
        warm=_hex_code(accent),
        text=_hex_code(text),
        text_muted=_hex_code(muted),
        text_inverse=_hex_code(inverse),
        line=_hex_code(line),
        surface=_hex_code(_WHITE),
        font_title=font_title,
        font_body=font_body,
        cover_title_pt=cover,
        cover_sub_pt=_clamp(cover * 0.40, 12.0, 20.0),
        cover_meta_pt=_clamp(footer + 1.0, 9.0, 14.0),
        section_title_pt=section,
        slide_title_pt=heading,
        body_pt=body,
        agenda_no_pt=_clamp(body + 1.0, 12.0, 20.0),
        closing_title_pt=_clamp(cover * 0.80, 24.0, 44.0),
        closing_body_pt=_clamp(body * 0.88, 10.0, 18.0),
        footer_pt=footer,
    )


def resolve_theme(name: str | Theme | None = None) -> Theme:
    if isinstance(name, Theme):
        return name
    if isinstance(name, str) and name in THEMES:
        return THEMES[name]
    return DEFAULT_THEME
