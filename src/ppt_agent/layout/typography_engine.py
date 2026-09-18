"""Typography engine: glyph-aware text measurement.

``styling.estimate_flow_height`` uses a flat ``width * 11`` chars-per-line
heuristic that underestimates CJK text (a full-width CJK glyph is about
``font_pt / 72`` inches wide, roughly twice an ASCII glyph). This engine
measures per-glyph: CJK ≈ 1.0 em, ASCII ≈ 0.55 em, whitespace ≈ 0.5 em.
Deterministic, no font files, no third-party deps.
"""

from __future__ import annotations

import math

DEFAULT_LINE_SPACING = 1.35
DEFAULT_PAD_IN = 0.12
MIN_FONT_PT = 12.0


def _glyph_em(character: str) -> float:
    """Width of one glyph in em units."""
    if not character.strip():
        return 0.5
    code = ord(character)
    if (
        0x2E80 <= code <= 0x9FFF      # CJK radicals through CJK unified
        or 0xF900 <= code <= 0xFAFF   # CJK compatibility
        or 0xFF00 <= code <= 0xFF60   # full-width forms
        or 0x3000 <= code <= 0x303F   # CJK punctuation
    ):
        return 1.0
    return 0.55


def _segment_lines(segment: str, width_in: float, font_pt: float) -> int:
    """Wrapped line count for one explicit (\\n-separated) segment."""
    if not segment:
        return 1
    em = font_pt / 72.0
    line_width = 0.0
    lines = 1
    for character in segment:
        glyph_width = _glyph_em(character) * em
        if line_width + glyph_width > width_in and line_width > 0:
            lines += 1
            line_width = glyph_width
        else:
            line_width += glyph_width
    return lines


def measure_text_block(
    text: str,
    width_in: float,
    font_pt: float,
    *,
    line_spacing: float = DEFAULT_LINE_SPACING,
    pad_in: float = DEFAULT_PAD_IN,
) -> float:
    """Height in inches a text block needs at ``width_in`` width."""
    if width_in <= 0:
        width_in = 1.0
    lines = sum(
        _segment_lines(segment, width_in, font_pt)
        for segment in str(text or "").split("\n")
    )
    lines = max(1, lines)
    line_height = font_pt / 72.0 * line_spacing
    return round(lines * line_height + pad_in, 3)


def shrink_to_fit(
    font_pt: float,
    needed_h: float,
    available_h: float,
    *,
    min_pt: float = MIN_FONT_PT,
) -> float:
    """Font size that fits ``needed_h`` into ``available_h``; never below min.

    Returns ``font_pt`` unchanged when it already fits. Pure arithmetic.
    """
    if needed_h <= 0 or available_h <= 0 or available_h >= needed_h:
        return font_pt
    factor = available_h / needed_h
    return round(max(min_pt, math.floor(font_pt * factor * 2) / 2), 1)
