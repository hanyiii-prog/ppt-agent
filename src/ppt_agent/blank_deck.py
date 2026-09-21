# -*- coding: utf-8 -*-
"""blank_deck -- Kimi-style: every page drawn from scratch on a Blank layout.

No template Layout/Master dependency.  Assets (logos + cover photo) are
extracted from the template file; all chrome (header wash, dots, divider,
logos) and content (cards, timelines, charts) are drawn with absolute
coordinates on every slide.

DNA-driven theming
------------------
Every colour and font used here comes from a :class:`Theme`.  ``theme_from_dna``
derives the theme from the template's extracted ``design_dna`` (``accent1``
brand colour, East-Asian font family, accent ramp), so swapping the template
reskins the whole deck.  ``DEFAULT_THEME`` is the built-in clinical-blue
fallback used only when no DNA is supplied -- it is *not* the happy path.  No
colour, font or gradient in a draw routine may be a bare hex literal: it must
resolve through ``t.*``.  Geometry (the calibrated inch coordinates) is
layout, not theme, so it stays as constants.
"""
from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ASSETS_DIR = Path(__file__).parent.parent.parent.parent / "assets"

FONT = "微软雅黑"
SLIDE_W = 13.333
SLIDE_H = 7.5

# -- absolute positions (calibrated from the template + Kimi's output) ------
BAR_H     = 0.71
DOT1      = (-0.20, 0.10, 0.46)
DOT2      = (0.10, 0.31, 0.27)
LOGO_H    = (10.06, 0.09, 1.99, 0.60)   # hospital logo (x, y, w, h)
LOGO_W    = (12.23, 0.04, 0.79, 0.71)   # wining logo
TITLE_X, TITLE_Y, TITLE_W, TITLE_H = 0.539, 0.147, 9.306, 0.436
LEAD_X, LEAD_Y, LEAD_W, LEAD_H = 0.556, 0.861, 12.222, 0.333
TOP       = 1.389
BOT       = 7.05
M         = 0.556


# ---- theme ------------------------------------------------------------------
@dataclass(frozen=True)
class Theme:
    """A complete visual identity for one deck, derived from the template DNA.

    Colour-only: geometry lives in the module constants above.  ``primary`` is
    the brand colour (``accent1``); the deep/soft/chip/divider variants are
    luminance steps of it, so a single brand hue drives the whole ramp.
    """

    primary: str = "0C67BC"
    primary_deep: str = "09437F"
    ink: str = "0D64BF"
    surface_soft: str = "F4F9FF"
    chip: str = "EAF4FF"
    divider: str = "BFD9F5"
    text: str = "262626"
    muted: str = "68737F"
    white: str = "FFFFFF"
    grad1: tuple[str, str] = ("0C67BC", "1687F1")
    grad2: tuple[str, str] = ("2B8FF0", "5EB0F8")
    grad3: tuple[str, str] = ("70B6FE", "9CCBFB")
    grad_warm: tuple[str, str] = ("F5A623", "FFBA55")
    grad_pale: tuple[str, str] = ("A9CFFB", "BDD9FA")
    font: str = "微软雅黑"


DEFAULT_THEME = Theme()


def _hex(value: Any) -> str | None:
    """Normalise a DNA colour token to bare upper hex, dropping ``#``/prefixes."""
    if not isinstance(value, str):
        return None
    text = value.strip().lstrip("#").replace("rgb:", "").replace("0x", "")
    if len(text) == 8:                 # RRGGBBAA -> keep RGB
        text = text[:6]
    text = text.upper()
    if len(text) != 6 or any(c not in "0123456789ABCDEF" for c in text):
        return None
    return text


def _rgb_tuple(hex_color: str) -> tuple[float, float, float]:
    return tuple(int(hex_color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _shift(hex_color: str, *, lightness: float | None = None,
           saturation: float | None = None) -> str:
    """Move a colour's HLS lightness/saturation toward a target (clamp 0..1)."""
    h, l, s = colorsys.rgb_to_hls(*_rgb_tuple(hex_color))
    if lightness is not None:
        l = min(1.0, max(0.0, lightness))
    if saturation is not None:
        s = min(1.0, max(0.0, saturation))
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def theme_from_dna(design_dna: Mapping[str, Any] | None) -> Theme:
    """Build a :class:`Theme` from a ``build_design_dna`` payload.

    Reads (in priority order) ``design_dna.color.named`` and the raw
    ``theme.colors`` OOXML scheme for the brand hue, ``theme.font_scheme`` for
    the East-Asian body font, and the accent ramp for warm gradients.  Falls
    back to ``DEFAULT_THEME`` field-by-field so a partial DNA still produces a
    coherent deck rather than a blank one.
    """
    if not isinstance(design_dna, Mapping):
        return DEFAULT_THEME

    scheme = dict((design_dna.get("theme") or {}).get("colors") or {})
    inner = design_dna.get("design_dna") or design_dna
    named = dict((inner.get("color") or {}).get("named") or {})

    def pick(*keys: str) -> str | None:
        for key in keys:
            hexv = _hex(named.get(key)) or _hex(scheme.get(key))
            if hexv:
                return hexv
        return None

    primary = pick("accent", "primary", "accent1") or DEFAULT_THEME.primary
    accent4 = pick("accent4")            # warm/orange in most templates

    ea_font = None
    font_scheme = (design_dna.get("theme") or {}).get("font_scheme") or {}
    for slot in ("minorFont", "majorFont"):
        cand = font_scheme.get(slot) or {}
        for key in ("ea", "cs", "latin"):
            value = cand.get(key)
            if isinstance(value, str) and value and value not in ("+mn-ea", "+mj-ea", "+mn-lt"):
                ea_font = value
                break
        if ea_font:
            break

    deep = _shift(primary, lightness=0.26)
    ink = _shift(primary, lightness=0.40, saturation=0.95)
    soft = _shift(primary, lightness=0.97, saturation=0.28)
    chip = _shift(primary, lightness=0.94, saturation=0.42)
    divider = _shift(primary, lightness=0.85, saturation=0.55)

    theme = Theme(
        primary=primary,
        primary_deep=deep,
        ink=ink,
        surface_soft=soft,
        chip=chip,
        divider=divider,
        grad1=(primary, _shift(primary, lightness=0.52, saturation=0.9)),
        grad2=(_shift(primary, lightness=0.55), _shift(primary, lightness=0.68)),
        grad3=(_shift(primary, lightness=0.72), _shift(primary, lightness=0.82)),
        grad_pale=(_shift(primary, lightness=0.80), _shift(primary, lightness=0.88)),
        font=ea_font or DEFAULT_THEME.font,
    )
    if accent4:
        theme = replace(theme, grad_warm=(accent4, _shift(accent4, lightness=0.66)))
    return theme


# ---- primitives -------------------------------------------------------------
def _rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color)


def _set_fill(shape, color: str):
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(color)
    shape.line.fill.background()


def _set_gradient(shape, stops: tuple[str, str], angle: int = 90):
    shape.fill.gradient()
    shape.fill.gradient_angle = angle
    gs = shape.fill.gradient_stops
    gs[0].color.rgb = _rgb(stops[0])
    gs[0].position = 0.0
    gs[1].color.rgb = _rgb(stops[1])
    gs[1].position = 1.0
    shape.line.fill.background()


def _box(slide, x: float, y: float, w: float, h: float, color: str,
         shape_type=MSO_SHAPE.RECTANGLE):
    sh = slide.shapes.add_shape(shape_type, Inches(x), Inches(y),
                                Inches(w), Inches(h))
    _set_fill(sh, color)
    return sh


def _grad_box(slide, x: float, y: float, w: float, h: float,
              stops: tuple[str, str], shape_type=MSO_SHAPE.RECTANGLE,
              angle: int = 90):
    sh = slide.shapes.add_shape(shape_type, Inches(x), Inches(y),
                                Inches(w), Inches(h))
    _set_gradient(sh, stops, angle)
    return sh


def _round(slide, x: float, y: float, w: float, h: float, *,
           fill: str | None = None, grad: tuple[str, str] | None = None,
           line: str | None = None, lw: float = 1.0, radius: float = 0.055):
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                Inches(x), Inches(y), Inches(w), Inches(h))
    try:
        sh.adjustments[0] = radius
    except Exception:
        pass
    if grad:
        _set_gradient(sh, grad)
    elif fill:
        _set_fill(sh, fill)
    else:
        sh.fill.background()
    if line:
        sh.line.color.rgb = _rgb(line)
        sh.line.width = Pt(lw)
    else:
        sh.line.fill.background()
    return sh


def _tb(slide, x: float, y: float, w: float, h: float, lines, *, t: Theme,
        size: int = 11, color: str | None = None, bold: bool = False,
        align: PP_ALIGN = PP_ALIGN.LEFT, anchor: MSO_ANCHOR = MSO_ANCHOR.TOP,
        spacing: float = 1.2, font: str | None = None):
    """Add a text box.  ``lines`` is a string or a list of strings."""
    if isinstance(lines, str):
        lines = [lines]
    color = color or t.text
    font = font or t.font
    tx = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tx.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    for i, line_text in enumerate(lines):
        if i > 0:
            tf.add_paragraph()
        p = tf.paragraphs[i]
        p.alignment = align
        p.space_after = Pt(0)
        p.line_spacing = spacing
        r = p.add_run()
        r.text = line_text
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.name = font
        r.font.color.rgb = _rgb(color)
    return tx


def _hair(slide, x: float, y: float, w: float, h: float, t: Theme,
          color: str | None = None):
    return _box(slide, x, y, w, h, color or t.divider)


def _icon(slide, x: float, y: float, size: float, color: str,
          shape: str = "cloud"):
    shape_map = {"cloud": MSO_SHAPE.CLOUD, "gear": MSO_SHAPE.GEAR_6,
                 "star": MSO_SHAPE.STAR_5_POINT, "heart": MSO_SHAPE.HEART,
                 "lightning": MSO_SHAPE.LIGHTNING_BOLT, "sun": MSO_SHAPE.SUN,
                 "moon": MSO_SHAPE.MOON, "smiley": MSO_SHAPE.SMILEY_FACE,
                 "diamond": MSO_SHAPE.DIAMOND, "hexagon": MSO_SHAPE.HEXAGON,
                 "triangle": MSO_SHAPE.ISOSCELES_TRIANGLE,
                 "pentagon": MSO_SHAPE.PENTAGON}
    st = shape_map.get(shape, MSO_SHAPE.CLOUD)
    sh = slide.shapes.add_shape(st, Inches(x), Inches(y), Inches(size), Inches(size))
    _set_fill(sh, color)
    return sh


def _number_badge(slide, x: float, y: float, size: float, label: str, *, t: Theme):
    """Gradient circle with a centred index -- gives cards visual hierarchy."""
    _grad_box(slide, x, y, size, size, t.grad1, MSO_SHAPE.OVAL)
    _tb(slide, x, y, size, size, str(label), t=t, size=max(9, int(size * 16)),
        color=t.white, bold=True, align=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE)


def _chip(slide, x: float, y: float, w: float, h: float, text: str, *, t: Theme):
    _round(slide, x, y, w, h, fill=t.chip, radius=0.20)
    _tb(slide, x + 0.05, y, w - 0.10, h, text, t=t, size=9, color=t.ink,
        bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

# ---- chrome -----------------------------------------------------------------
def add_chrome(slide, *, t: Theme, logos_dir: Path | None = None):
    """Draw header wash, dots, divider, and both logos on a Blank slide."""
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0,
                                  Inches(SLIDE_W), Inches(BAR_H))
    bar.fill.gradient()
    bar.fill.gradient_angle = 0
    gs = bar.fill.gradient_stops
    gs[0].color.rgb = _rgb(t.primary)
    gs[0].position = 0.0
    gs[0].color.brightness = 0.15
    gs[1].color.rgb = _rgb(t.primary)
    gs[1].position = 1.0
    gs[1].color.brightness = 1.0
    bar.line.fill.background()
    for (dx, dy, ds) in [DOT1, DOT2]:
        d = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(dx), Inches(dy),
                                    Inches(ds), Inches(ds))
        _set_gradient(d, (t.chip, t.primary), 315)
    _hair(slide, 0, BAR_H, SLIDE_W, 0.012, t, t.primary)
    ld = logos_dir or ASSETS_DIR
    hosp = ld / "logo_hospital.png"
    win  = ld / "logo_wining.png"
    if hosp.exists():
        slide.shapes.add_picture(str(hosp), Inches(LOGO_H[0]), Inches(LOGO_H[1]),
                                  Inches(LOGO_H[2]), Inches(LOGO_H[3]))
    if win.exists():
        slide.shapes.add_picture(str(win), Inches(LOGO_W[0]), Inches(LOGO_W[1]),
                                  Inches(LOGO_W[2]), Inches(LOGO_W[3]))


def content_header(slide, title: str, lead: str | None = None, *,
                   t: Theme, logos_dir: Path | None = None) -> float:
    """Draw the chrome header + title + optional lead.  Returns content top."""
    add_chrome(slide, t=t, logos_dir=logos_dir)
    _tb(slide, TITLE_X, TITLE_Y, TITLE_W, TITLE_H, title, t=t,
        size=20, color=t.primary_deep, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    if lead:
        _tb(slide, LEAD_X, LEAD_Y, LEAD_W, LEAD_H, lead, t=t,
            size=14, color=t.ink, bold=True)
    return TOP


# ---- page types -------------------------------------------------------------
def draw_cover(slide, *, t: Theme, pill: str = "汇报", title: str = "",
               meta: str = "", logos_dir: Path | None = None,
               photo: Path | None = None):
    """Cover page: photo + 2 wash bands + logos + pill + title + meta."""
    ld = logos_dir or ASSETS_DIR
    pp = photo or (ld / "cover_photo.jpg")
    if pp.exists():
        slide.shapes.add_picture(str(pp), 0, Inches(-0.07),
                                  Inches(SLIDE_W), Inches(4.20))
    for (by, bh, a) in [(2.5, 1.80, 40), (3.5, 0.80, 30)]:
        band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(by),
                                       Inches(SLIDE_W), Inches(bh))
        band.fill.gradient()
        band.fill.gradient_angle = 270
        gs = band.fill.gradient_stops
        gs[0].color.rgb = _rgb(t.primary)
        gs[0].position = 0.0
        gs[0].color.brightness = 1.0 - a / 100.0
        gs[1].color.rgb = _rgb(t.primary)
        gs[1].position = 1.0
        gs[1].color.brightness = 1.0
        band.line.fill.background()
    hosp = ld / "logo_hospital.png"
    win  = ld / "logo_wining.png"
    if hosp.exists():
        slide.shapes.add_picture(str(hosp), Inches(LOGO_H[0]), Inches(LOGO_H[1]),
                                  Inches(LOGO_H[2]), Inches(LOGO_H[3]))
    if win.exists():
        slide.shapes.add_picture(str(win), Inches(LOGO_W[0]), Inches(LOGO_W[1]),
                                  Inches(LOGO_W[2]), Inches(LOGO_W[3]))
    # pill
    pill_shape = _grad_box(slide, 4.38, 4.81, 4.87, 0.61, t.grad1,
                            MSO_SHAPE.ROUNDED_RECTANGLE)
    try:
        pill_shape.adjustments[0] = 0.10
    except Exception:
        pass
    _tb(slide, 4.67, 4.91, 4.29, 0.40, pill, t=t, size=24, color=t.white,
        bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    # title (single or multi-line, centred)
    if title:
        _tb(slide, 1.11, 5.62, 11.41, 1.20, title.splitlines() or [title], t=t,
            size=40, color=t.primary_deep, bold=True, align=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE, spacing=1.15)
    if meta:
        _tb(slide, 2.50, 6.85, 8.64, 0.36, meta, t=t, size=16,
            color=t.primary_deep, align=PP_ALIGN.CENTER)


def draw_toc(slide, items: list[dict[str, str]], *, t: Theme,
             title: str = "目录", title_en: str = "CONTENTS",
             logos_dir: Path | None = None):
    """TOC page: left panel with title, right side numbered items."""
    add_chrome(slide, t=t, logos_dir=logos_dir)
    _tb(slide, 0.83, 1.67, 3.06, 0.83, title, t=t, size=36, color=t.primary_deep,
        bold=True)
    _tb(slide, 0.86, 2.58, 3.06, 0.31, title_en, t=t, size=14, color=t.divider,
        bold=True)
    _hair(slide, 0.86, 3.08, 0.78, 0.07, t, t.primary)
    _grad_box(slide, 9.72, 4.44, 4.44, 4.44, t.grad3, MSO_SHAPE.OVAL, 315)
    y = 1.50
    pitch = 1.25
    for i, item in enumerate(items[:5]):
        num = item.get("num") or f"{i+1:02d}"
        _grad_box(slide, 4.58, y, 0.75, 0.75, t.grad1, MSO_SHAPE.OVAL)
        _tb(slide, 4.58, y, 0.75, 0.75, num, t=t, size=14, color=t.white,
            bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        _tb(slide, 5.61, y, 6.67, 0.42, item.get("title", ""), t=t, size=18,
            color=t.primary_deep, bold=True)
        sub = item.get("sub", "")
        if sub:
            _tb(slide, 5.61, y + 0.44, 6.67, 0.28, sub, t=t, size=11,
                color=t.muted)
        if i < len(items[:5]) - 1:
            _hair(slide, 4.58, y + 1.00, 7.92, 0.01, t)
        y += pitch


def draw_section(slide, title: str, lines: list[str], *, t: Theme,
                 chapter_num: str = "", logos_dir: Path | None = None):
    """Section divider: gradient number panel + title + subtitle lines."""
    add_chrome(slide, t=t, logos_dir=logos_dir)
    pw, ph = 4.40, 3.00
    py = 2.10
    _grad_box(slide, M, py, pw, ph, t.grad1, MSO_SHAPE.ROUNDED_RECTANGLE, 315)
    if chapter_num:
        _tb(slide, M, py + 0.30, pw, 1.60, chapter_num, t=t, size=88,
            color=t.white, bold=True, align=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE)
        # thin rule under the number, inside the panel
        _hair(slide, M + pw / 2 - 0.60, py + 2.15, 1.20, 0.05, t, t.white)
        if lines:
            _tb(slide, M + 0.45, py + 2.30, pw - 0.90, 0.55, lines[0], t=t,
                size=12.5, color=t.white, align=PP_ALIGN.CENTER)
        tx, tw = M + pw + 0.55, SLIDE_W - (M + pw + 0.55) - M
    else:
        tx, tw = M, SLIDE_W - 2 * M
    _tb(slide, tx, py + 0.55, tw, 0.90, title, t=t, size=40, color=t.primary_deep,
        bold=True, anchor=MSO_ANCHOR.MIDDLE)
    _hair(slide, tx, py + 1.60, 1.30, 0.06, t, t.primary)
    rest = lines[1:] if chapter_num and lines else lines
    if rest:
        _tb(slide, tx, py + 1.85, tw, 1.30, rest, t=t, size=14, color=t.muted,
            spacing=1.5)

def draw_closing(slide, *, t: Theme, title: str = "谢谢",
                 sub: str = "请各位领导批评指正", meta: str = "",
                 logos_dir: Path | None = None, photo: Path | None = None):
    """Closing page: same visual as cover but with closing text."""
    ld = logos_dir or ASSETS_DIR
    pp = photo or (ld / "cover_photo.jpg")
    if pp.exists():
        slide.shapes.add_picture(str(pp), 0, Inches(-0.07),
                                  Inches(SLIDE_W), Inches(4.20))
    for (by, bh, a) in [(2.5, 1.80, 40), (3.5, 0.80, 30)]:
        band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(by),
                                       Inches(SLIDE_W), Inches(bh))
        band.fill.gradient()
        band.fill.gradient_angle = 270
        gs = band.fill.gradient_stops
        gs[0].color.rgb = _rgb(t.primary)
        gs[0].position = 0.0
        gs[0].color.brightness = 1.0 - a / 100.0
        gs[1].color.rgb = _rgb(t.primary)
        gs[1].position = 1.0
        gs[1].color.brightness = 1.0
        band.line.fill.background()
    hosp = ld / "logo_hospital.png"
    win  = ld / "logo_wining.png"
    if hosp.exists():
        slide.shapes.add_picture(str(hosp), Inches(LOGO_H[0]), Inches(LOGO_H[1]),
                                  Inches(LOGO_H[2]), Inches(LOGO_H[3]))
    if win.exists():
        slide.shapes.add_picture(str(win), Inches(LOGO_W[0]), Inches(LOGO_W[1]),
                                  Inches(LOGO_W[2]), Inches(LOGO_W[3]))
    _tb(slide, 1.11, 4.20, 11.41, 0.89, title, t=t, size=36, color=t.primary_deep,
        bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    if sub:
        _tb(slide, 2.50, 5.30, 8.64, 0.50, sub, t=t, size=18, color=t.ink,
            align=PP_ALIGN.CENTER)
    if meta:
        _tb(slide, 2.50, 6.00, 8.64, 0.36, meta, t=t, size=13, color=t.muted,
            align=PP_ALIGN.CENTER)


# ---- content kits -----------------------------------------------------------
def _wrap_count(text: str, size_pt: float, box_w: float) -> int:
    """Estimate how many visual lines ``text`` occupies in a box ``box_w`` inches wide."""
    if not text:
        return 0
    text = str(text)
    if chr(10) in text:
        return sum(_wrap_count(ln, size_pt, box_w) for ln in text.split(chr(10))) or 1
    char_w = size_pt / 72.0  # 全角近似：CJK 字宽 ~= 字号
    cap = max(1, int(box_w / char_w))
    units = sum(1.0 if ord(ch) > 0x2E80 else 0.55 for ch in text)
    return max(1, math.ceil(units / cap))


def _lines_of(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [ln for ln in value.splitlines() if ln]
    return [ln for ln in value if ln]


def _block_height(lines, size_pt: float, box_w: float, spacing: float = 1.3) -> float:
    if isinstance(lines, str):
        lines = [lines]
    rows = sum(_wrap_count(ln, size_pt, box_w) for ln in lines)
    return rows * size_pt / 72.0 * spacing



_COL_GAP = {1: 0, 2: 0.40, 3: 0.25, 4: 0.20, 5: 0.15, 6: 0.12}
_ICON_SHAPES = {"cloud", "gear", "star", "heart", "lightning", "sun", "moon",
                "smiley", "diamond", "hexagon", "triangle", "pentagon"}


def _card_icon(slide, x, y, size, *, t: Theme, shape: str, index: int):
    """A gradient badge: a real shape when named, else an index number."""
    _grad_box(slide, x, y, size, size, t.grad1, MSO_SHAPE.OVAL)
    if shape in _ICON_SHAPES:
        _icon(slide, x + size * 0.28, y + size * 0.28, size * 0.44, t.white, shape)
    else:
        _tb(slide, x, y, size, size, "%02d" % index, t=t, size=int(size * 14),
            color=t.white, bold=True, align=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE)


def kit_quad_cards(slide, cards, note=None, *, t: Theme, title="", lead=None,
                   logos_dir=None):
    """2x2 grid of icon cards sized to content and vertically centred."""
    top = content_header(slide, title, lead, t=t, logos_dir=logos_dir)
    reserve = 1.05 if note else 0.0
    avail = BOT - top - reserve
    cw, gap_x, gap_y = 5.972, 0.396, 0.24
    pad = 0.554
    shown = cards[:4]
    need = []
    for c in shown:
        body = _lines_of(c.get("body", ""))
        bh = _block_height(body, 10.5, cw - pad, 1.35) if body else 0.0
        need.append(1.05 + bh + 0.22)
    row0 = max(need[0:2]) if len(need) >= 2 else (need[0] if need else 1.6)
    row1 = max(need[2:4]) if len(need) >= 4 else (need[2] if len(need) == 3 else 0.0)
    total = row0 + row1 + (gap_y if row1 else 0.0)
    y0 = top + max(0.0, (avail - total) / 2)
    for i, c in enumerate(shown):
        col, r = i % 2, (0 if i < 2 else 1)
        ch = row0 if r == 0 else row1
        x = M + col * (cw + gap_x)
        y = y0 if r == 0 else y0 + row0 + gap_y
        _round(slide, x, y, cw, ch, fill=t.white, line=t.divider, lw=1.0)
        _card_icon(slide, x + 0.277, y + 0.250, 0.556, t=t,
                   shape=c.get("icon", "cloud"), index=i + 1)
        _tb(slide, x + 1.000, y + 0.250, cw - 1.222, 0.556, c.get("title", ""),
            t=t, size=15, color=t.primary_deep, bold=True,
            anchor=MSO_ANCHOR.MIDDLE)
        body = _lines_of(c.get("body", ""))
        if body:
            _tb(slide, x + 0.277, y + 1.00, cw - 0.554, ch - 1.15, body, t=t,
                size=10.5, color=t.text, spacing=1.35)
    if note:
        ny = BOT - 0.83
        _round(slide, M, ny, SLIDE_W - 2*M, 0.83, fill=t.chip, radius=0.04)
        _tb(slide, M + 0.20, ny + 0.10, SLIDE_W - 2*M - 0.40, 0.63, note, t=t,
            size=10.5, color=t.ink, spacing=1.3)

def kit_column_cards(slide, cards, *, t: Theme, cols=None, title="", lead=None,
                     logos_dir=None):
    """N equal columns sized to content, top-aligned in the body."""
    top = content_header(slide, title, lead, t=t, logos_dir=logos_dir)
    n = max(1, cols or len(cards))
    gap = _COL_GAP.get(n, 0.15)
    w = (SLIDE_W - 2*M - gap * (n - 1)) / n
    ramps = [t.grad1, t.grad2, t.grad3]
    head_h = 0.90
    shown = cards[:n]
    need = []
    for c in shown:
        lines = _lines_of(c.get("lines", []))
        bh = _block_height(lines, 11, w - 0.36, 1.5) if lines else 0.0
        need.append(head_h + 0.28 + bh + 0.28)
    avail = BOT - top
    card_h = min(avail, max(3.20, max(need) if need else 3.20))
    y0 = top + max(0.0, (avail - card_h) / 2)
    for i, c in enumerate(shown):
        x = M + i * (w + gap)
        _round(slide, x, y0, w, card_h, fill=t.white, line=t.divider, lw=1.0)
        _grad_box(slide, x, y0, w, head_h, ramps[i % 3])
        _tb(slide, x + 0.05, y0, w - 0.10, head_h, c.get("title", ""), t=t,
            size=14, color=t.white, bold=True, align=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE)
        lines = _lines_of(c.get("lines", []))
        if lines:
            _tb(slide, x + 0.18, y0 + head_h + 0.28, w - 0.36,
                card_h - head_h - 0.40, lines, t=t, size=11.5, color=t.text,
                spacing=1.6, anchor=MSO_ANCHOR.MIDDLE)


def kit_progress_timeline(slide, steps, note=None, *, t: Theme, title="",
                          lead=None, logos_dir=None):
    """Dated rows with status chips (done/doing/plan)."""
    top = content_header(slide, title, lead, t=t, logos_dir=logos_dir)
    status_grad = {"done": t.grad1, "doing": t.grad_warm, "plan": t.grad_pale}
    y = top + 0.10
    shown = steps[:6]
    pitch = min(1.10, (BOT - top - 0.20) / max(1, len(shown)))
    for i, s in enumerate(shown):
        st = s.get("status", "done")
        g = status_grad.get(st, t.grad1)
        _grad_box(slide, M, y, 1.60, 0.36, g, MSO_SHAPE.ROUNDED_RECTANGLE)
        _tb(slide, M + 0.05, y, 1.50, 0.36, s.get("date", ""), t=t, size=10,
            color=t.white, bold=True, align=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE)
        _tb(slide, M + 1.85, y, 4.5, 0.36, s.get("title", ""), t=t, size=12,
            color=t.primary_deep, bold=True)
        desc = s.get("desc", "")
        if desc:
            _tb(slide, M + 6.5, y, SLIDE_W - M*2 - 6.5, pitch - 0.10, desc, t=t,
                size=10, color=t.text, spacing=1.25)
        if i < len(shown) - 1:
            _hair(slide, M + 0.80, y + 0.40, 0.012, pitch - 0.44, t)
        y += pitch
    if note:
        _round(slide, M, BOT - 0.83, SLIDE_W - 2*M, 0.83, fill=t.chip, radius=0.04)
        _tb(slide, M + 0.20, BOT - 0.73, SLIDE_W - 2*M - 0.40, 0.63, note, t=t,
            size=10.5, color=t.ink)


def kit_stage_timeline(slide, stages, current=None, note=None, *, t: Theme,
                       title="", lead=None, logos_dir=None):
    """Arrow stages with an optional 'current' banner."""
    top = content_header(slide, title, lead, t=t, logos_dir=logos_dir)
    n = max(1, len(stages))
    gap = 0.12
    w = (SLIDE_W - 2*M - gap * (n - 1)) / n
    ramps = [t.grad1, t.grad2, t.grad3]
    for i, s in enumerate(stages[:3]):
        x = M + i * (w + gap)
        sh = slide.shapes.add_shape(MSO_SHAPE.PENTAGON, Inches(x), Inches(top),
                                     Inches(w), Inches(1.10))
        _set_gradient(sh, ramps[i % 3])
        _tb(slide, x + 0.15, top + 0.10, w - 0.30, 0.40, s.get("head", ""), t=t,
            size=14, color=t.white, bold=True)
        desc = s.get("desc", "")
        if desc:
            _tb(slide, x + 0.15, top + 0.55, w - 0.30, 0.50, desc, t=t, size=9,
                color=t.white, spacing=1.2)
    cy = top + 1.40
    if current:
        _grad_box(slide, M, cy, SLIDE_W - 2*M, 0.50, t.grad_warm,
                  MSO_SHAPE.ROUNDED_RECTANGLE)
        _tb(slide, M + 0.20, cy, SLIDE_W - 2*M - 0.40, 0.50, current, t=t,
            size=14, color=t.white, bold=True, align=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE)
    if note:
        ny = BOT - 0.83
        _round(slide, M, ny, SLIDE_W - 2*M, 0.83, fill=t.chip, radius=0.04)
        _tb(slide, M + 0.20, ny + 0.10, SLIDE_W - 2*M - 0.40, 0.63, note, t=t,
            size=10.5, color=t.ink)


def kit_two_panel_list(slide, left, right, *, t: Theme, title="", lead=None,
                       logos_dir=None):
    """Two bordered panels with icon rows."""
    top = content_header(slide, title, lead, t=t, logos_dir=logos_dir)
    pw = (SLIDE_W - 2*M - 0.40) / 2
    ph = BOT - top
    for j, panel in enumerate([left, right]):
        px = M + j * (pw + 0.40)
        _round(slide, px, top, pw, ph, fill=t.white, line=t.divider, lw=1.0)
        _grad_box(slide, px, top, pw, 0.55, t.grad1 if j == 0 else t.grad2)
        _tb(slide, px + 0.15, top, pw - 0.30, 0.55, panel.get("title", ""), t=t,
            size=14, color=t.white, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        rows = panel.get("rows", [])
        ry = top + 0.75
        for (head, desc) in rows[:5]:
            _tb(slide, px + 0.15, ry, pw - 0.30, 0.30, head, t=t, size=11,
                color=t.primary_deep, bold=True)
            if desc:
                _tb(slide, px + 0.15, ry + 0.30, pw - 0.30, 0.45, desc, t=t,
                    size=9.5, color=t.text, spacing=1.2)
            ry += 0.85


def kit_stage_cards(slide, stages, tasks=None, *, t: Theme, task_title=None,
                    title="", lead=None, logos_dir=None):
    """Stage cards across top + numbered task list, centred as a block."""
    top = content_header(slide, title, lead, t=t, logos_dir=logos_dir)
    n = max(1, len(stages))
    gap = _COL_GAP.get(n, 0.15)
    w = (SLIDE_W - 2*M - gap * (n - 1)) / n
    ramps = [t.grad1, t.grad2, t.grad3]
    shown = stages[:4]
    need = []
    for s in shown:
        desc = _lines_of(s.get("desc", ""))
        bh = _block_height(desc, 9, w - 0.30, 1.3) if desc else 0.0
        need.append(0.72 + bh + 0.15)
    card_h = max(1.20, max(need) if need else 1.20)
    half = (max(0, len(tasks or [])) + 1) // 2
    block_h = card_h + (0.30 + (0.45 + half * 0.45 if tasks else 0))
    avail = BOT - top
    y0 = top + max(0.0, min(0.45, (avail - block_h) / 2))
    for i, s in enumerate(shown):
        x = M + i * (w + gap)
        _grad_box(slide, x, y0, w, card_h, ramps[i % 3],
                  MSO_SHAPE.ROUNDED_RECTANGLE)
        _tb(slide, x + 0.15, y0 + 0.14, w - 0.30, 0.45, s.get("head", ""), t=t,
            size=13, color=t.white, bold=True)
        desc = _lines_of(s.get("desc", ""))
        if desc:
            _tb(slide, x + 0.15, y0 + 0.62, w - 0.30, card_h - 0.72, desc, t=t,
                size=9, color=t.white, spacing=1.3)
    if tasks:
        ty = y0 + card_h + 0.32
        if task_title:
            _tb(slide, M, ty, SLIDE_W - 2*M, 0.36, task_title, t=t, size=14,
                color=t.primary_deep, bold=True)
            ty += 0.48
        half = (len(tasks) + 1) // 2
        col_w = (SLIDE_W - 2*M - 0.40) / 2
        for j, task in enumerate(tasks[:8]):
            col = j // half
            row = j % half
            x = M + col * (col_w + 0.40)
            y = ty + row * 0.46
            num = task.get("no", str(j + 1)) if isinstance(task, dict) else str(j + 1)
            _grad_box(slide, x, y, 0.32, 0.32, t.grad1, MSO_SHAPE.OVAL)
            _tb(slide, x, y, 0.32, 0.32, num, t=t, size=9, color=t.white,
                bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
            text = task.get("text", "") if isinstance(task, dict) else str(task)
            owner = task.get("owner", "") if isinstance(task, dict) else ""
            label = text + (("　" + owner) if owner else "")
            _tb(slide, x + 0.42, y, col_w - 0.42, 0.32, label, t=t, size=10,
                color=t.text)

def kit_four_role_cards(slide, cards, note=None, *, t: Theme, title="",
                        lead=None, logos_dir=None):
    """Four role cards sized to content, top-aligned in the body."""
    top = content_header(slide, title, lead, t=t, logos_dir=logos_dir)
    n = 4
    gap = _COL_GAP.get(n, 0.20)
    w = (SLIDE_W - 2*M - gap * (n - 1)) / n
    ramps = [t.grad1, t.grad2, t.grad3, t.grad1]
    head_h = 0.55
    shown = cards[:4]
    need = []
    for c in shown:
        body = _lines_of(c.get("body", ""))
        bh = _block_height(body, 11, w - 0.36, 1.5) if body else 0.0
        need.append(head_h + 0.24 + bh + 0.24)
    avail = BOT - top
    card_h = min(avail, max(2.55, max(need) if need else 2.55))
    y0 = top + max(0.0, (avail - card_h) / 2)
    for i, c in enumerate(shown):
        x = M + i * (w + gap)
        _round(slide, x, y0, w, card_h, fill=t.white, line=t.divider, lw=1.0)
        _grad_box(slide, x, y0, w, head_h, ramps[i % 4])
        _tb(slide, x + 0.05, y0, w - 0.10, head_h, c.get("title", ""), t=t,
            size=14, color=t.white, bold=True, align=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE)
        body = _lines_of(c.get("body", ""))
        if body:
            _tb(slide, x + 0.18, y0 + head_h + 0.26, w - 0.36,
                card_h - head_h - 0.38, body, t=t, size=11.5, color=t.text,
                spacing=1.6, anchor=MSO_ANCHOR.MIDDLE)
    if note:
        ny = BOT - 0.83
        _round(slide, M, ny, SLIDE_W - 2*M, 0.83, fill=t.chip, radius=0.04)
        _tb(slide, M + 0.20, ny + 0.10, SLIDE_W - 2*M - 0.40, 0.63, note, t=t,
            size=10.5, color=t.ink)


def kit_org_chart(slide, top_node, groups, depts, note=None, *, t: Theme,
                  title="", lead=None, logos_dir=None):
    """Hierarchical org chart."""
    top = content_header(slide, title, lead, t=t, logos_dir=logos_dir)
    tw = 4.0
    tx = (SLIDE_W - tw) / 2
    _grad_box(slide, tx, top, tw, 0.60, t.grad1, MSO_SHAPE.ROUNDED_RECTANGLE)
    _tb(slide, tx + 0.10, top, tw - 0.20, 0.60, top_node.get("title", ""), t=t,
        size=14, color=t.white, bold=True, align=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE)
    bus_y = top + 0.85
    _hair(slide, SLIDE_W/2, top + 0.60, 0.012, 0.25, t)
    _hair(slide, M, bus_y, SLIDE_W - 2*M, 0.012, t)
    n = max(1, len(groups))
    gap = _COL_GAP.get(n, 0.20)
    gw = (SLIDE_W - 2*M - gap * (n - 1)) / n
    gy = bus_y + 0.25
    for i, g in enumerate(groups[:4]):
        x = M + i * (gw + gap)
        _hair(slide, x + gw/2, bus_y, 0.012, 0.25, t)
        _grad_box(slide, x, gy, gw, 0.45, t.grad2, MSO_SHAPE.ROUNDED_RECTANGLE)
        _tb(slide, x + 0.05, gy, gw - 0.10, 0.45, g.get("title", ""), t=t,
            size=11, color=t.white, bold=True, align=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE)
    dy = gy + 0.65
    dh = BOT - dy - (0.90 if note else 0)
    for i, d in enumerate(depts[:4]):
        x = M + i * (gw + gap)
        _round(slide, x, dy, gw, dh, fill=t.surface_soft, line=t.divider, lw=0.75)
        _tb(slide, x + 0.08, dy + 0.08, gw - 0.16, 0.35, d.get("title", ""), t=t,
            size=10.5, color=t.primary_deep, bold=True)
        body = d.get("body", "")
        if body:
            _tb(slide, x + 0.08, dy + 0.48, gw - 0.16, dh - 0.58, body, t=t,
                size=9, color=t.text, spacing=1.25)
    if note:
        ny = BOT - 0.83
        _round(slide, M, ny, SLIDE_W - 2*M, 0.83, fill=t.chip, radius=0.04)
        _tb(slide, M + 0.20, ny + 0.10, SLIDE_W - 2*M - 0.40, 0.63, note, t=t,
            size=10.5, color=t.ink)


# ---- main renderer -----------------------------------------------------------
KIT_MAP = {
    "quad_cards": kit_quad_cards,
    "column_cards": kit_column_cards,
    "progress_timeline": kit_progress_timeline,
    "stage_timeline": kit_stage_timeline,
    "two_panel_list": kit_two_panel_list,
    "stage_cards": kit_stage_cards,
    "four_role_cards": kit_four_role_cards,
    "org_chart": kit_org_chart,
}


def render_blank_deck(pages, output, *, assets_dir=None, theme=None,
                      design_dna=None):
    """Render a page plan on Blank layouts (Kimi approach).

    The visual identity comes from ``theme`` (a :class:`Theme`) or, when absent,
    from ``design_dna`` via :func:`theme_from_dna`.  Passing neither falls back
    to ``DEFAULT_THEME`` -- acceptable only for tests/CI, never for a real deck.
    """
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    blank = prs.slide_layouts[6]  # Blank layout
    ld = assets_dir or ASSETS_DIR
    if theme is None:
        theme = theme_from_dna(design_dna)
    t = theme
    warnings: list[str] = []

    for idx, spec in enumerate(pages, 1):
        slide = prs.slides.add_slide(blank)
        role = spec.get("role", "content")
        if role == "cover":
            draw_cover(slide, t=t, pill=spec.get("pill", "汇报"),
                       title=spec.get("title", ""), meta=spec.get("meta", ""),
                       logos_dir=ld)
        elif role == "toc":
            draw_toc(slide, spec.get("items", []), t=t,
                     title=spec.get("title", "目录"),
                     title_en=spec.get("title_en", "CONTENTS"), logos_dir=ld)
        elif role == "section":
            draw_section(slide, spec.get("title", ""), spec.get("lines", []),
                         t=t, chapter_num=spec.get("chapter_num", ""),
                         logos_dir=ld)
        elif role == "closing":
            draw_closing(slide, t=t, title=spec.get("title", "谢谢"),
                         sub=spec.get("sub", ""), meta=spec.get("meta", ""),
                         logos_dir=ld)
        else:
            kit = spec.get("kit", "")
            fn = KIT_MAP.get(kit)
            if fn is None:
                warnings.append(f"page {idx}: unknown kit {kit!r}; skipped")
                continue
            try:
                fn(slide, t=t, logos_dir=ld,
                   **{k: v for k, v in spec.items()
                      if k not in ("role", "kit")})
            except TypeError as exc:
                warnings.append(f"page {idx}: kit {kit!r} error: {exc}")

    prs.save(str(output))
    return {"output": str(output), "pages": len(pages), "warnings": warnings,
            "theme": {"primary": t.primary, "font": t.font}}
