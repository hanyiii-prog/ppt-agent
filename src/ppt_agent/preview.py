"""Rasterise a rendered PPTX into PNG previews.

The sandbox has no LibreOffice, which normally means "you cannot see what you
rendered". This module closes that loop with Pillow alone: it reads the
produced ``.pptx`` and paints each slide, so a human (or a critic loop) can
judge whether a deck is actually designed.

It is a *fidelity preview*, not a pixel-perfect PowerPoint clone. Geometry,
fills, outlines, text size, colour, alignment and wrapping are reproduced
faithfully enough to review layout; PowerPoint-only effects (gradients,
shadows, 3-D) are approximated.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

EMU_PER_INCH = 914400
DEFAULT_DPI = 96.0
# Fraction of the font size used as the distance between consecutive baselines.
_LINE_SPACING = 1.34

_FONT_FILES: dict[bool, tuple[str, ...]] = {
    False: (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ),
    True: (
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
}
_FONT_CACHE: dict[tuple[int, bool], Any] = {}


def _font(size_px: float, bold: bool) -> Any:
    key = (max(int(round(size_px)), 1), bool(bold))
    cached = _FONT_CACHE.get(key)
    if cached is not None:
        return cached
    font = None
    for path in _FONT_FILES[bool(bold)]:
        try:
            font = ImageFont.truetype(path, key[0], index=0)
            break
        except Exception:
            font = None
    if font is None:
        font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _rgb_of(color: Any) -> tuple[int, int, int] | None:
    try:
        value = color.rgb
    except Exception:
        return None
    if value is None:
        return None
    text = str(value)
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except (ValueError, IndexError):
        return None


def _wrap(text: str, font: Any, max_px: float) -> list[str]:
    lines: list[str] = []
    for raw in str(text).split("\n"):
        if not raw:
            lines.append("")
            continue
        current = ""
        for char in raw:
            candidate = current + char
            try:
                width = font.getlength(candidate)
            except Exception:
                width = len(candidate) * font.size * 0.6
            if current and width > max_px:
                lines.append(current)
                current = char
            else:
                current = candidate
        lines.append(current)
    return lines or [""]


def _alpha_of(element: Any, tag: str) -> float:
    """Read an ``a:alpha`` value (0-100000) under the first matching colour."""
    from pptx.oxml.ns import qn

    holder = element.find(qn(tag))
    if holder is None:
        return 1.0
    color = holder.find(qn("a:srgbClr"))
    if color is None:
        color = holder.find(qn("a:schemeClr"))
    if color is None:
        return 1.0
    alpha = color.find(qn("a:alpha"))
    if alpha is None:
        return 1.0
    try:
        return max(0.0, min(1.0, int(alpha.get("val", "100000")) / 100000.0))
    except (TypeError, ValueError):
        return 1.0


def _fill_of(shape: Any) -> tuple[tuple[int, int, int] | None, float]:
    try:
        fill = shape.fill
        fill_type = str(fill.type)
    except Exception:
        return None, 1.0
    if "SOLID" not in fill_type.upper():
        return None, 1.0
    rgb = _rgb_of(fill.fore_color)
    if rgb is None:
        return None, 1.0
    try:
        alpha = _alpha_of(shape._element.spPr, "a:solidFill")
    except Exception:
        alpha = 1.0
    return rgb, alpha


def _line_of(shape: Any, dpi: float) -> tuple[tuple[int, int, int] | None, float]:
    try:
        line = shape.line
        if line.fill.type is None:
            return None, 0.0
        fill_type = str(line.fill.type)
    except Exception:
        return None, 0.0
    if "SOLID" not in fill_type.upper():
        return None, 0.0
    rgb = _rgb_of(line.color)
    if rgb is None:
        return None, 0.0
    try:
        width_emu = float(line.width) if line.width is not None else 12700.0
    except Exception:
        width_emu = 12700.0
    return rgb, max(1.0, width_emu / EMU_PER_INCH * dpi)


def _is_oval(shape: Any) -> bool:
    try:
        from pptx.oxml.ns import qn

        geom = shape._element.spPr.find(qn("a:prstGeom"))
        return geom is not None and str(geom.get("prst", "")).lower() in ("ellipse", "oval", "circle")
    except Exception:
        return False


def _slide_background(slide: Any) -> tuple[int, int, int] | None:
    try:
        from pptx.oxml.ns import qn

        bg = slide._element.find(qn("p:cSld")).find(qn("p:bg"))
        if bg is None:
            return None
        solid = bg.find(qn("p:bgPr")).find(qn("a:solidFill"))
        if solid is None:
            return None
        color = solid.find(qn("a:srgbClr"))
        if color is None:
            return None
        text = str(color.get("val", ""))
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except Exception:
        return None


def _paint_text(draw: Any, shape: Any, scale: float, dpi: float) -> None:
    left = float(shape.left) * scale
    top = float(shape.top) * scale
    width = max(float(shape.width) * scale, 8.0)
    frame = shape.text_frame
    wrap = frame.word_wrap is not False
    cursor = top

    for paragraph in frame.paragraphs:
        runs = list(paragraph.runs)
        text = "".join(run.text for run in runs)
        base = runs[0] if runs else None
        size_pt = 18.0
        bold = False
        rgb = (0, 0, 0)
        if base is not None:
            try:
                if base.font.size is not None:
                    size_pt = float(base.font.size.pt)
            except Exception:
                pass
            bold = bool(base.font.bold)
            rgb = _rgb_of(base.font.color) or (0, 0, 0)
        size_px = size_pt * dpi / 72.0
        font = _font(size_px, bold)
        line_h = size_px * _LINE_SPACING

        if not text:
            cursor += line_h
            continue

        lines = _wrap(text, font, width) if wrap else text.split("\n")
        alignment = str(paragraph.alignment or "").upper()
        for line in lines:
            try:
                line_w = font.getlength(line)
            except Exception:
                line_w = len(line) * size_px * 0.6
            if "CENTER" in alignment:
                x = left + (width - line_w) / 2
            elif "RIGHT" in alignment:
                x = left + width - line_w
            else:
                x = left
            draw.text((x, cursor), line, font=font, fill=rgb)
            cursor += line_h


def _paint_shape(draw: Any, shape: Any, scale: float, dpi: float) -> None:
    left = float(shape.left) * scale
    top = float(shape.top) * scale
    width = float(shape.width) * scale
    height = float(shape.height) * scale
    box = [left, top, left + width, top + height]
    oval = _is_oval(shape)

    fill_rgb, alpha = _fill_of(shape)
    if fill_rgb is not None and alpha > 0.01:
        color = (*fill_rgb, int(round(alpha * 255)))
        if oval:
            draw.ellipse(box, fill=color)
        else:
            draw.rectangle(box, fill=color)

    line_rgb, line_w = _line_of(shape, dpi)
    if line_rgb is not None and line_w > 0:
        if oval:
            draw.ellipse(box, outline=line_rgb, width=int(round(line_w)))
        else:
            draw.rectangle(box, outline=line_rgb, width=int(round(line_w)))


def _paint_picture(slide_image: Image.Image, shape: Any, scale: float) -> None:
    try:
        blob = shape.image.blob
        asset = Image.open(io.BytesIO(blob)).convert("RGBA")
    except Exception:
        return
    target_w = max(int(round(float(shape.width) * scale)), 1)
    target_h = max(int(round(float(shape.height) * scale)), 1)
    asset.thumbnail((target_w, target_h), Image.LANCZOS)
    slide_image.paste(
        asset,
        (int(round(float(shape.left) * scale)), int(round(float(shape.top) * scale))),
        asset,
    )


def rasterize_pptx(
    pptx_path: str | Path,
    output_dir: str | Path | None = None,
    *,
    dpi: float = DEFAULT_DPI,
    prefix: str | None = None,
) -> list[Path]:
    """Paint every slide of ``pptx_path`` to a PNG and return the written paths."""
    from pptx import Presentation

    source = Path(pptx_path)
    if not source.exists():
        raise FileNotFoundError(f"pptx not found: {source}")
    destination = Path(output_dir) if output_dir else source.parent / f"{source.stem}-preview"
    destination.mkdir(parents=True, exist_ok=True)

    deck = Presentation(str(source))
    scale = dpi / EMU_PER_INCH
    width_px = max(int(round(float(deck.slide_width) * scale)), 16)
    height_px = max(int(round(float(deck.slide_height) * scale)), 16)
    stem = prefix or source.stem

    written: list[Path] = []
    for index, slide in enumerate(deck.slides, 1):
        canvas = Image.new("RGB", (width_px, height_px), (255, 255, 255))
        background = _slide_background(slide)
        if background is not None:
            canvas.paste(Image.new("RGB", (width_px, height_px), background), (0, 0))
        draw = ImageDraw.Draw(canvas, "RGBA")
        for shape in slide.shapes:
            try:
                if getattr(shape, "shape_type", None) is not None and "PICTURE" in str(shape.shape_type):
                    _paint_picture(canvas, shape, scale)
                    continue
                if shape.has_text_frame or "AUTO_SHAPE" in str(getattr(shape, "shape_type", "")):
                    _paint_shape(draw, shape, scale, dpi)
                if shape.has_text_frame and shape.text_frame.text.strip():
                    _paint_text(draw, shape, scale, dpi)
            except Exception:
                continue
        path = destination / f"{stem}-{index:02d}.png"
        canvas.save(path)
        written.append(path)
    return written
