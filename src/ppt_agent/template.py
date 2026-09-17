"""Legacy v0.3 extractors.

``analyze_pptx`` now delegates to :mod:`ppt_agent.page_dna` (schema
``template-dna/v0.4``), which walks the full rendered layer stack per page kind
and captures rotation / per-stop gradient alpha / run-level colour alpha.

The helpers below are kept because they are part of the public surface: the
shape-level record and the fill record are unit-tested directly and are still
useful for one-off, shape-at-a-time inspection.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import hashlib
import re
import zipfile
import xml.etree.ElementTree as ET

EMU_PER_INCH = 914400
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _hex_rgb(color: Any) -> str | None:
    try:
        rgb = color.rgb
        return str(rgb) if rgb else None
    except (AttributeError, ValueError, TypeError):
        return None


def _xml_alpha(element: Any) -> int | None:
    try:
        node = element.find(f"{{{A_NS}}}alpha")
        if node is not None and node.get("val") is not None:
            return int(node.get("val"))
    except (AttributeError, TypeError, ValueError):
        pass
    return None


def _xml_alpha_from_shape(shape: Any) -> int | None:
    try:
        xml = shape._element.xml
    except Exception:
        return None
    match = re.search(r"<a:alpha(?:ModFix|Off)?[^>]*val=[\"'](\d+)[\"']", xml)
    return int(match.group(1)) if match else None


def _fill_info(shape: Any) -> dict[str, Any]:
    fill = getattr(shape, "fill", None)
    if fill is None:
        return {"type": "none"}
    try:
        fill_type = str(fill.type).split(".")[-1].lower()
    except Exception:
        fill_type = "unknown"
    info: dict[str, Any] = {"type": fill_type}
    try:
        rgb = _hex_rgb(fill.fore_color)
        if rgb:
            info["rgb"] = rgb
    except Exception:
        pass
    alpha = None
    try:
        sp_pr = shape._element.spPr
        solid = sp_pr.find(f"{{{A_NS}}}solidFill")
        if solid is not None:
            color = next(iter(solid), None)
            alpha = _xml_alpha(color) if color is not None else None
        grad = sp_pr.find(f"{{{A_NS}}}gradFill")
        if grad is not None:
            info["gradient_xml"] = ET.tostring(grad, encoding="unicode")
    except Exception:
        pass
    transparency: float | None
    try:
        transparency = float(fill.transparency)
    except (AttributeError, TypeError, ValueError):
        transparency = None
    # python-pptx's resolved transparency is authoritative when exposed; only fall
    # back to regex-scraping the raw OOXML when the high-level API hides it.
    if alpha is None and transparency is None:
        alpha = _xml_alpha_from_shape(shape)
    if transparency is not None:
        info["transparency"] = round(transparency, 4)
        info["alpha"] = round((1 - transparency) * 100000)
        info["opacity"] = round(1 - transparency, 4)
    elif alpha is not None:
        info["alpha"] = alpha
        info["opacity"] = round(alpha / 100000, 4)
        info["transparency"] = round(1 - alpha / 100000, 4)
    return info


def _line_info(shape: Any) -> dict[str, Any]:
    line = getattr(shape, "line", None)
    if line is None:
        return {"type": "none"}
    info: dict[str, Any] = {}
    try:
        info["width_pt"] = round(line.width.pt, 2) if line.width else None
    except Exception:
        pass
    try:
        info["rgb"] = _hex_rgb(line.color)
    except Exception:
        pass
    try:
        info["dash_style"] = str(line.dash_style).split(".")[-1]
    except Exception:
        pass
    try:
        info["transparency"] = round(float(line.transparency), 4)
    except Exception:
        pass
    return info


def _font_info(run: Any) -> dict[str, Any]:
    font = run.font
    result: dict[str, Any] = {}
    if font.name:
        result["name"] = font.name
    if font.size:
        result["size_pt"] = round(font.size.pt, 1)
    for attr in ("bold", "italic", "underline"):
        value = getattr(font, attr, None)
        if value is not None:
            result[attr] = bool(value)
    try:
        result["rgb"] = _hex_rgb(font.color)
    except Exception:
        pass
    return result


def _text_info(shape: Any) -> dict[str, Any] | None:
    if not getattr(shape, "has_text_frame", False):
        return None
    tf = shape.text_frame
    paragraphs: list[dict[str, Any]] = []
    fonts: list[dict[str, Any]] = []
    for paragraph in tf.paragraphs:
        p: dict[str, Any] = {
            "alignment": str(paragraph.alignment).split(".")[-1] if paragraph.alignment else None,
            "level": paragraph.level,
            "runs": [],
        }
        for run in paragraph.runs:
            fi = _font_info(run)
            if fi:
                fonts.append(fi)
            p["runs"].append({"text": run.text, "font": fi})
        paragraphs.append(p)
    info: dict[str, Any] = {
        "text": shape.text,
        "paragraph_count": len(tf.paragraphs),
        "paragraphs": paragraphs,
        "fonts": fonts,
    }
    for attr in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        try:
            value = getattr(tf, attr)
            info[attr] = round(value / EMU_PER_INCH, 4)
        except Exception:
            pass
    try:
        info["word_wrap"] = bool(tf.word_wrap)
    except Exception:
        pass
    try:
        info["vertical_anchor"] = str(tf.vertical_anchor).split(".")[-1]
    except Exception:
        pass
    return info


def _placeholder_info(shape: Any) -> dict[str, Any] | None:
    if not getattr(shape, "is_placeholder", False):
        return None
    try:
        ph = shape.placeholder_format
        return {"idx": ph.idx, "type": str(ph.type).split(".")[-1]}
    except Exception:
        return {"type": "unknown"}


def _background_info(slide_or_master: Any) -> dict[str, Any]:
    try:
        fill = slide_or_master.background.fill
        info: dict[str, Any] = {"type": str(fill.type).split(".")[-1].lower()}
        rgb = _hex_rgb(fill.fore_color)
        if rgb:
            info["rgb"] = rgb
        return info
    except Exception:
        return {"type": "unknown"}


def _shape_type(shape: Any) -> str:
    try:
        return str(shape.shape_type).split(".")[-1]
    except Exception:
        return "unknown"


def _fidelity_info(shape: Any) -> dict[str, Any]:
    """Capture raw OOXML so unsupported PowerPoint features are not discarded."""
    info: dict[str, Any] = {}
    try:
        xml = shape._element.xml
        info["xml_sha256"] = hashlib.sha256(xml.encode("utf-8")).hexdigest()
        info["raw_xml"] = xml
        info["custom_geometry"] = "custGeom" in xml
        info["gradient_fill"] = "gradFill" in xml
        info["alpha_transforms"] = bool(re.search(r"<a:alpha(?:ModFix|Off)?", xml))
        info["blip_embeds"] = re.findall(r"r:embed=\"([^\"]+)\"", xml)
        info["blip_links"] = re.findall(r"r:link=\"([^\"]+)\"", xml)
        info["has_effects"] = any(token in xml for token in ("effectLst", "effectDag", "outerShdw", "glow"))
        info["has_transform_2d"] = "xfrm" in xml
    except Exception:
        pass
    return info


def _inheritance_info(slide_or_layout: Any) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for attr in ("follow_master_graphics", "preserve", "show_master_shapes", "follow_master_background"):
        try:
            value = getattr(slide_or_layout, attr)
            info[attr] = bool(value) if value is not None else None
        except Exception:
            pass
    return info


def _shape_record(shape: Any, z_index: int, parent_id: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": str(getattr(shape, "shape_id", "")),
        "name": getattr(shape, "name", None),
        "type": _shape_type(shape),
        "z_index": z_index,
        "z_order": z_index,
        "parent_id": parent_id,
        "geometry": {},
        "style": {"fill": _fill_info(shape), "line": _line_info(shape)},
        "fidelity": _fidelity_info(shape),
    }
    for attr in ("left", "top", "width", "height"):
        try:
            record["geometry"][attr] = round(getattr(shape, attr) / EMU_PER_INCH, 4)
        except Exception:
            pass
    for attr in ("rotation", "flip_horizontal", "flip_vertical"):
        try:
            record["geometry"][attr] = getattr(shape, attr)
        except Exception:
            pass
    text = _text_info(shape)
    if text is not None:
        record["text"] = text
    placeholder = _placeholder_info(shape)
    if placeholder:
        record["placeholder"] = placeholder
    try:
        record["is_group"] = bool(shape.shape_type == 6)
    except Exception:
        record["is_group"] = False
    children = getattr(shape, "shapes", None)
    if record["is_group"] and children is not None:
        record["children"] = [_shape_record(child, child_index, record["id"]) for child_index, child in enumerate(children)]
    return record


def _theme_colors(path: Path) -> dict[str, str]:
    ns = {"a": A_NS}
    result: dict[str, str] = {}
    try:
        with zipfile.ZipFile(path) as zf:
            theme_names = [n for n in zf.namelist() if re.search(r"theme\d+\.xml$", n)]
            if not theme_names:
                return result
            root = ET.fromstring(zf.read(theme_names[0]))
            clr_scheme = root.find(".//a:clrScheme", ns)
            if clr_scheme is None:
                return result
            for child in list(clr_scheme):
                value = next(iter(child), None)
                if value is not None and value.get("val"):
                    result[child.tag.rsplit("}", 1)[-1]] = value.get("val")
    except (OSError, ET.ParseError, zipfile.BadZipFile):
        return {}
    return result


def _layout_signature(slide: Any) -> dict[str, Any]:
    types: Counter[str] = Counter(); placeholders: Counter[str] = Counter()
    for shape in slide.shapes:
        types[_shape_type(shape)] += 1
        ph = _placeholder_info(shape)
        if ph:
            placeholders[str(ph.get("type"))] += 1
    return {"shape_types": dict(types), "placeholders": dict(placeholders)}


def _extract_master(master: Any) -> dict[str, Any]:
    layouts = []
    for layout in master.slide_layouts:
        layouts.append({
            "name": layout.name,
            "type": str(getattr(layout, "type", "")).split(".")[-1],
            "inheritance": _inheritance_info(layout),
            "background": _background_info(layout),
            "shapes": [_shape_record(s, i) for i, s in enumerate(layout.shapes)],
            "raw_layout_xml": getattr(layout._element, "xml", None),
        })
    return {
        "name": master.name,
        "background": _background_info(master),
        "inheritance": _inheritance_info(master),
        "shapes": [_shape_record(s, i) for i, s in enumerate(master.shapes)],
        "layouts": layouts,
        "raw_master_xml": getattr(master._element, "xml", None),
    }


def _dominant_palette(path: Path) -> dict:
    """Area-weighted, schemeClr-resolved palette -- what the deck *looks* like.
    Delegates to :mod:`ppt_agent.palette`; safe to import (stdlib only)."""
    try:
        from .palette import dominant_colors
        return dominant_colors(str(path))
    except Exception:
        return {}


def analyze_pptx(
    path: str | Path,
    *,
    include_raw_xml: bool = True,
    kind_overrides: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Extract semantic + fidelity Template DNA from a PPTX.

    ``template-dna/v0.4``. The heavy lifting lives in :mod:`ppt_agent.page_dna`,
    which extracts DNA **per page kind** (cover / toc / section / content /
    closing) over the full rendered layer stack (master -> layout -> slide)
    rather than one flat shape list. Every v0.3 key is still emitted.

    ``include_raw_xml=False`` drops the raw OOXML blobs (keeps the hashes) for
    large decks; ``kind_overrides`` maps 1-based slide numbers to a kind when
    the layout names are not descriptive enough to classify a page.
    """
    from .page_dna import extract_deck_dna

    return extract_deck_dna(
        path, include_raw_xml=include_raw_xml, kind_overrides=kind_overrides
    )
