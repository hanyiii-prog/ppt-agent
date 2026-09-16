from __future__ import annotations

import base64
import html
import mimetypes
from pathlib import Path
from typing import Any

from ..ir import Presentation
from ..styling import (
    TEXT_COMPONENT_TYPES,
    LayoutBox,
    font_style_of,
    group_children,
    normalize_alignment,
    normalize_color,
    normalize_opacity,
    resolve_layout,
    slide_size_inches,
    text_of,
)
from .base import Renderer, RenderError, RenderRequest, RenderResult

PX_PER_INCH = 96.0
MAX_INLINE_ASSET_BYTES = 4 * 1024 * 1024

_TEXT_CLASS = {
    "title": "t-title",
    "heading": "t-title",
    "subtitle": "t-subtitle",
    "quote": "t-quote",
    "caption": "t-caption",
    "label": "t-caption",
}


def _css_length(inches: float) -> str:
    return f"{inches * PX_PER_INCH:.2f}px"


def _rgba(rgb: str, opacity: float | None) -> str:
    red, green, blue = (int(rgb[i : i + 2], 16) for i in (0, 2, 4))
    if opacity is None or opacity >= 1.0:
        return f"#{rgb}"
    return f"rgba({red},{green},{blue},{opacity:.4f})"


def _surface_css(component: Any) -> str:
    """Background + border declarations shared by text boxes and generic shapes."""
    style = component.style if isinstance(component.style, dict) else {}
    declarations: list[str] = []

    fill = style.get("fill")
    if isinstance(fill, dict) and fill:
        rgb = normalize_color(fill.get("rgb"))
        if rgb is not None:
            declarations.append(f"background-color:{_rgba(rgb, normalize_opacity(fill))}")
        elif (str(fill.get("type") or "").lower() in {"none", "background"}):
            declarations.append("background-color:transparent")

    line = style.get("line")
    if isinstance(line, dict) and line:
        border_rgb = normalize_color(line.get("rgb"))
        width = line.get("width_pt")
        if border_rgb is not None or isinstance(width, (int, float)):
            color = f"#{border_rgb}" if border_rgb else "#000000"
            thickness = float(width) if isinstance(width, (int, float)) and width > 0 else 1.0
            declarations.append(f"border:{thickness:.2f}pt solid {color}")

    return (";" + ";".join(declarations)) if declarations else ""


def _font_css(component: Any, font_pt: float) -> str:
    font = font_style_of(component)
    declarations = [f"font-size:{float(font_pt):.2f}pt"]
    if isinstance(font.get("bold"), bool):
        declarations.append(f"font-weight:{'700' if font['bold'] else '400'}")
    if isinstance(font.get("italic"), bool):
        declarations.append(f"font-style:{'italic' if font['italic'] else 'normal'}")
    if isinstance(font.get("name"), str) and font["name"].strip():
        declarations.append(f"font-family:{html.escape(font['name'].strip(), quote=True)},sans-serif")
    color = normalize_color(font.get("rgb"))
    if color is not None:
        declarations.append(f"color:#{color}")
    alignment = normalize_alignment(font.get("alignment"))
    if alignment is not None:
        declarations.append(f"text-align:{alignment}")
    return ";" + ";".join(declarations)


def _position_css(box: LayoutBox, *, fixed_height: bool) -> str:
    height = f"height:{_css_length(box.h)};" if fixed_height else f"min-height:{_css_length(box.h)};"
    return (
        f"left:{_css_length(box.x)};top:{_css_length(box.y)};"
        f"width:{_css_length(box.w)};{height}"
    )


def _text_html(box: LayoutBox) -> str:
    component = box.component
    ctype = (component.type or "text").lower()
    text = html.escape(text_of(component), quote=True).replace("\n", "<br>")
    classes = f"comp text {_TEXT_CLASS.get(ctype, 't-body')}"
    return f'<div class="{classes}" style="{_position_css(box, fixed_height=False)}{_font_css(component, box.font_pt)}{_surface_css(component)}">{text}</div>'


def _image_html(box: LayoutBox, warnings: list[str]) -> str:
    component = box.component
    data = component.data if isinstance(component.data, dict) else {}
    source, warning = _image_source(data, component)
    if warning:
        warnings.append(warning)
    label = html.escape(str(data.get("name") or component.id or "image"), quote=True)
    if source is None:
        return _placeholder_html(box, f"[image] {label}")
    alt = html.escape(str(data.get("alt") or label), quote=True)
    return (
        f'<div class="comp image" style="{_position_css(box, fixed_height=True)}">'
        f'<img src="{source}" alt="{alt}"></div>'
    )


def _image_source(data: dict[str, Any], component: Any) -> tuple[str | None, str | None]:
    blob = data.get("bytes") or data.get("image") or data.get("blob")
    if isinstance(blob, (bytes, bytearray)):
        media = str(data.get("media_type") or "image/png")
        return f"data:{media};base64,{base64.b64encode(bytes(blob)).decode('ascii')}", None
    path = data.get("path") if isinstance(data.get("path"), str) else None
    if not path:
        return None, None
    asset = Path(path)
    if not asset.exists():
        return None, f"image not found: {path}"
    if asset.stat().st_size <= MAX_INLINE_ASSET_BYTES:
        media = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(asset.read_bytes()).decode("ascii")
        return f"data:{media};base64,{encoded}", None
    return asset.as_uri(), f"image inlined as a file URI (larger than {MAX_INLINE_ASSET_BYTES} bytes): {path}"


def _table_html(box: LayoutBox) -> str:
    component = box.component
    data = component.data if isinstance(component.data, dict) else {}
    rows = data.get("rows")
    if not (isinstance(rows, list) and rows and all(isinstance(row, (list, tuple)) for row in rows)):
        return _placeholder_html(box, f"[table] {html.escape(str(data.get('name') or component.id or ''), quote=True)}".strip())
    columns = max(len(row) for row in rows)
    body: list[str] = []
    for index, row in enumerate(rows):
        tag = "th" if index == 0 else "td"
        cells = "".join(
            f"<{tag}>{html.escape('' if column >= len(row) else str(row[column]), quote=True)}</{tag}>"
            for column in range(columns)
        )
        body.append(f"<tr>{cells}</tr>")
    return (
        f'<div class="comp table" style="{_position_css(box, fixed_height=True)}">'
        f"<table>{''.join(body)}</table></div>"
    )


def _placeholder_html(box: LayoutBox, label: str) -> str:
    return (
        f'<div class="comp placeholder" style="{_position_css(box, fixed_height=True)}">'
        f"{html.escape(label, quote=True)}</div>"
    )


def _shape_html(box: LayoutBox) -> str:
    component = box.component
    style = component.style if isinstance(component.style, dict) else {}
    radius = "border-radius:50%;" if str(style.get("shape") or "").lower() in ("ellipse", "oval", "circle") else ""
    text = html.escape(text_of(component), quote=True).replace("\n", "<br>")
    inner = f'<span class="shape-text">{text}</span>' if text else ""
    return (
        f'<div class="comp shape" style="{_position_css(box, fixed_height=True)}{radius}'
        f'{_surface_css(component)}{_font_css(component, box.font_pt)}">{inner}</div>'
    )


def _component_html(box: LayoutBox, warnings: list[str]) -> str:
    ctype = (box.component.type or "shape").lower()
    if ctype in TEXT_COMPONENT_TYPES:
        return _text_html(box)
    if ctype == "image":
        return _image_html(box, warnings)
    if ctype == "table":
        return _table_html(box)
    if ctype == "chart":
        data = box.component.data if isinstance(box.component.data, dict) else {}
        name = html.escape(str(data.get("name") or box.component.id or ""), quote=True)
        return _placeholder_html(box, f"[chart] {name}".strip())
    if ctype == "group":
        children = group_children(box.component)
        rendered = [
            _component_html(
                LayoutBox(
                    child,
                    float(child.x),
                    float(child.y),
                    max(float(child.w), 0.05),
                    max(float(child.h), 0.05),
                    box.font_pt,
                    True,
                ),
                warnings,
            )
            for child in children
            if all(isinstance(getattr(child, key, None), (int, float)) for key in ("x", "y", "w", "h"))
        ]
        if rendered:
            return "".join(rendered)
        return _placeholder_html(box, f"[group] {box.component.id or ''}".strip())
    return _shape_html(box)


def _background_css(slide_data: Any) -> str:
    if not isinstance(slide_data, dict):
        return ""
    background = slide_data.get("background")
    if not isinstance(background, dict):
        return ""
    fill = background.get("fill") if isinstance(background.get("fill"), dict) else background
    if not isinstance(fill, dict):
        return ""
    rgb = normalize_color(fill.get("rgb"))
    if rgb is None:
        return ""
    return f' style="background-color:{_rgba(rgb, normalize_opacity(fill))}"'


def _slide_html(slide: Any, width_in: float, height_in: float, warnings: list[str]) -> str:
    purpose = (slide.purpose or "content").lower()
    notes = ""
    if slide.speaker_notes:
        notes = f'<aside class="notes">{html.escape(str(slide.speaker_notes), quote=True)}</aside>'
    body = "".join(_component_html(box, warnings) for box in resolve_layout(slide, width_in, height_in))
    slide_id = html.escape(str(slide.id), quote=True)
    return (
        f'<section class="slide" id="{slide_id}" data-purpose="{html.escape(purpose, quote=True)}"'
        f'{_background_css(slide.data)}>{notes}{body}</section>'
    )


def _stylesheet(width_in: float, height_in: float) -> str:
    return f"""
:root {{ color-scheme: light; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: #eef0f4; }}
.deck {{ display: flex; flex-direction: column; align-items: center; gap: 20px; padding: 24px 0; }}
.slide {{
  position: relative; width: var(--slide-w); height: var(--slide-h); flex: 0 0 auto;
  background: #ffffff; overflow: hidden;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.16);
  font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
  color: #111827;
}}
.comp {{ position: absolute; }}
.comp.text {{ display: flex; flex-direction: column; justify-content: flex-start;
  line-height: 1.35; word-wrap: break-word; overflow-wrap: anywhere; }}
.t-title {{ font-size: 36pt; font-weight: 700; }}
.t-subtitle {{ font-size: 24pt; }}
.t-body {{ font-size: 20pt; }}
.t-caption {{ font-size: 12pt; }}
.t-quote {{ font-size: 20pt; font-style: italic; border-left: 3pt solid #d4d4d8; padding-left: 10px; }}
.comp.shape {{ display: flex; align-items: flex-start; }}
.shape-text {{ display: block; padding: 2px 4px; }}
.comp.placeholder {{ display: flex; align-items: center; justify-content: center;
  border: 1px dashed #a3a3a3; color: #8a8a8a; font-size: 12pt; background: rgba(0, 0, 0, 0.02); }}
.comp.image img {{ width: 100%; height: 100%; object-fit: contain; display: block; }}
.comp.table table {{ width: 100%; border-collapse: collapse; font-size: 12pt; }}
.comp.table th, .comp.table td {{ border: 1px solid #d4d4d8; padding: 4px 6px; text-align: left; vertical-align: top; }}
.notes {{ position: absolute; left: -100000px; top: 0; width: 1px; height: 1px; overflow: hidden; }}
@media print {{
  html, body {{ background: #ffffff; }}
  .deck {{ gap: 0; padding: 0; }}
  .slide {{ box-shadow: none; break-after: page; page-break-after: always; }}
  .slide:last-child {{ break-after: auto; page-break-after: auto; }}
  @page {{ size: {width_in:.4f}in {height_in:.4f}in; margin: 0; }}
}}
""".strip()


def render_html_deck(presentation: Presentation, output: str | Path) -> tuple[Path, list[str]]:
    """Render Universal IR into a single self-contained, printable HTML deck."""
    from ..design import design_presentation

    presentation = design_presentation(presentation)
    width_in, height_in = slide_size_inches(presentation)
    width_px = round(width_in * PX_PER_INCH)
    height_px = round(height_in * PX_PER_INCH)
    warnings: list[str] = []

    parts = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="generator" content="ppt-agent">',
        f"<title>{html.escape(str(presentation.title or 'Presentation'), quote=True)}</title>",
        f"<style>{_stylesheet(width_in, height_in)}</style>",
        "</head>",
        "<body>",
        f'<main class="deck" data-slide-count="{len(presentation.slides)}"'
        f' style="--slide-w:{width_px}px;--slide-h:{height_px}px">',
    ]
    for slide in presentation.slides:
        parts.append(_slide_html(slide, width_in, height_in, warnings))
    parts.extend(["</main>", "</body>", "</html>", ""])

    destination = Path(output)
    from ..textio import write_text_lf

    write_text_lf(destination, "\n".join(parts))
    return destination, warnings


class HtmlRenderer(Renderer):
    """Portable visual engine: IR -> one self-contained printable HTML deck."""

    name = "html"
    display_name = "Visual Engine (HTML)"
    media_type = "text/html"
    extension = ".html"
    editable = False
    requires = ()
    capabilities = (
        "deterministic",
        "flow-layout",
        "print-ready",
        "self-contained",
        "preview-enabled",
    )

    def render(self, presentation: Presentation, request: RenderRequest) -> RenderResult:
        if not isinstance(presentation, Presentation):
            raise RenderError("html renderer expects a Presentation IR instance")
        path, warnings = render_html_deck(presentation, request.output)
        return RenderResult(
            renderer=self.name,
            path=str(path),
            slide_count=len(presentation.slides),
            editable=False,
            media_type=self.media_type,
            capabilities=self.capabilities,
            warnings=warnings,
            metrics={"bytes": path.stat().st_size if path.exists() else 0},
        )
