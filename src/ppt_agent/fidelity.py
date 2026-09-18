"""OOXML fidelity extraction: the evidence layer for the Fidelity Engine.

This module is deliberately stdlib-only (zipfile + ElementTree). It reads a real
PPTX package and extracts, for one slide, the complete Master/Layout/Slide
evidence chain: per-element identity (``sp``/``pic``/``graphicFrame``/
``cxnSp``/``grpSp`` via their own ``cNvPr``), full transforms (rotation, flip,
group child-coordinate mapping, rotation-aware rendered bboxes), structured
fill/line/gradient/effect/alpha, typography and body properties, custom
geometry, connectors, tables, theme colour resolution, placeholder inheritance
resolution and a page-kind classification.

The semantic Template DNA extractor (``page_dna``) is intended for reasoning;
this layer preserves package-level information required for high-fidelity
reconstruction, diffing and property-level repair.
"""
from __future__ import annotations

import hashlib
import json
import math
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"p": P_NS, "a": A_NS, "r": R_NS}

# keep serialized raw_xml readable and stable across extractions
ET.register_namespace("a", A_NS)
ET.register_namespace("p", P_NS)
ET.register_namespace("r", R_NS)
ET.register_namespace("", PR_NS)

SCHEMA = "template-dna/fidelity/v2"

_SHAPE_KINDS = {"sp", "pic", "graphicFrame", "cxnSp", "grpSp"}
_NV_PATHS = {
    "sp": "./p:nvSpPr/p:cNvPr",
    "pic": "./p:nvPicPr/p:cNvPr",
    "graphicFrame": "./p:nvGraphicFramePr/p:cNvPr",
    "cxnSp": "./p:nvCxnSpPr/p:cNvPr",
    "grpSp": "./p:nvGrpSpPr/p:cNvPr",
}
_GROUP_PROPS = {
    "sp": "./p:spPr",
    "pic": "./p:spPr",
    "graphicFrame": "./p:xfrm",
    "cxnSp": "./p:spPr",
    "grpSp": "./p:grpSpPr",
}
_XFRM_PATHS = {
    "sp": "./p:spPr/a:xfrm",
    "pic": "./p:spPr/a:xfrm",
    "graphicFrame": "./p:xfrm",
    "cxnSp": "./p:spPr/a:xfrm",
    "grpSp": "./p:grpSpPr/a:xfrm",
}
_EA_TAGS = ("cNvGrpSpPr", "cNvSpPr", "cNvPicPr", "cNvGraphicFramePr", "cNvCxnSpPr", "nvGrpSpPr", "nvSpPr", "nvPicPr", "nvGraphicFramePr", "nvCxnSpPr", "grpSpPr", "spPr", "style", "txBody", "xfrm", "blipFill", "prstGeom", "custGeom", "graphic")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _rel_map(xml_bytes: bytes) -> dict[str, str]:
    root = ET.fromstring(xml_bytes)
    return {node.get("Id"): node.get("Target") for node in root if node.get("Id")}


def _zip_path(base_dir: str, target: str) -> str:
    return posixpath.normpath(posixpath.join(base_dir, target)).lstrip("/")


def _int(attrib: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(round(float(attrib.get(key, default))))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# transform / geometry
# --------------------------------------------------------------------------- #
def _xfrm_record(xfrm: ET.Element | None) -> dict[str, Any] | None:
    if xfrm is None:
        return None
    off = xfrm.find("./a:off", NS)
    ext = xfrm.find("./a:ext", NS)
    if off is None or ext is None:
        return None
    record: dict[str, Any] = {
        "x": _int(off.attrib, "x"),
        "y": _int(off.attrib, "y"),
        "cx": _int(ext.attrib, "cx"),
        "cy": _int(ext.attrib, "cy"),
        "rotation": round(_int(xfrm.attrib, "rot") / 60000.0, 4),
        "flip_h": xfrm.get("flipH") == "1",
        "flip_v": xfrm.get("flipV") == "1",
    }
    ch_off = xfrm.find("./a:chOff", NS)
    ch_ext = xfrm.find("./a:chExt", NS)
    if ch_off is not None and ch_ext is not None:
        record["child_offset"] = {"x": _int(ch_off.attrib, "x"), "y": _int(ch_off.attrib, "y")}
        record["child_extent"] = {"cx": _int(ch_ext.attrib, "cx"), "cy": _int(ch_ext.attrib, "cy")}
    return record


def rotated_bbox_emu(x: float, y: float, w: float, h: float, rotation: float) -> tuple[float, float, float, float]:
    """Axis-aligned bbox of a rect rotated by ``rotation`` degrees about its centre."""
    theta = math.radians(rotation % 360.0)
    cos_a, sin_a = abs(math.cos(theta)), abs(math.sin(theta))
    rw = w * cos_a + h * sin_a
    rh = w * sin_a + h * cos_a
    cx, cy = x + w / 2.0, y + h / 2.0
    return (cx - rw / 2.0, cy - rh / 2.0, rw, rh)


def _map_into_group(geom: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    """Map a child rect from the group child-coordinate space into group space."""
    ch = group.get("child_extent") or {"cx": group["cx"], "cy": group["cy"]}
    cho = group.get("child_offset") or {"x": group["x"], "y": group["y"]}
    sx = (group["cx"] / ch["cx"]) if ch["cx"] else 1.0
    sy = (group["cy"] / ch["cy"]) if ch["cy"] else 1.0
    mapped = dict(geom)
    mapped["x"] = group["x"] + (geom["x"] - cho["x"]) * sx
    mapped["y"] = group["y"] + (geom["y"] - cho["y"]) * sy
    mapped["cx"] = geom["cx"] * sx
    mapped["cy"] = geom["cy"] * sy
    return mapped


def _resolve_geometry(element: ET.Element, kind: str, ancestors: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Full transform chain: own xfrm mapped through every enclosing group."""
    xfrm = element.find(_XFRM_PATHS[kind], NS)
    geom = _xfrm_record(xfrm)
    if geom is None:
        return None
    for group in ancestors:
        geom = _map_into_group(geom, group)
    bb_x, bb_y, bb_w, bb_h = rotated_bbox_emu(geom["x"], geom["y"], geom["cx"], geom["cy"], geom["rotation"])
    geom["rendered_bbox"] = {
        "x": round(bb_x, 2),
        "y": round(bb_y, 2),
        "cx": round(bb_w, 2),
        "cy": round(bb_h, 2),
    }
    return geom


# --------------------------------------------------------------------------- #
# colour / alpha / fill / line / effects
# --------------------------------------------------------------------------- #
def _alpha_list(el: ET.Element) -> list[float]:
    out = []
    for child in el:
        tag = _local(child.tag)
        if tag in ("alpha", "alphaModFix"):
            # a:alpha uses val, a:alphaModFix uses amt
            raw = child.get("val") if child.get("val") is not None else child.get("amt")
            try:
                out.append(round(float(raw) / 100000.0, 6))
            except (TypeError, ValueError):
                pass
        elif tag == "alphaOff":
            try:
                out.append(round(-_int(child.attrib, "val") / 100000.0, 6))
            except (TypeError, ValueError):
                pass
    return out


def _color_record(el: ET.Element | None, theme_ctx: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if el is None:
        return None
    for child in el:
        tag = _local(child.tag)
        record: dict[str, Any]
        if tag == "srgbClr":
            record = {"rgb": (child.get("val") or "").upper()}
        elif tag == "schemeClr":
            token = child.get("val") or ""
            record = {"scheme": token}
            if theme_ctx:
                resolved = resolve_scheme_color(token, theme_ctx)
                if resolved:
                    record["resolved_rgb"] = resolved
        elif tag == "sysClr":
            record = {"system": child.get("val") or "", "rgb": (child.get("lastClr") or "000000").upper()}
        elif tag == "prstClr":
            record = {"preset": child.get("val") or ""}
        elif tag == "scrgbClr":
            record = {"scrgb": [child.get("r"), child.get("g"), child.get("b")]}
        elif tag == "hslClr":
            record = {"hsl": [child.get("h"), child.get("s"), child.get("l")]}
        else:
            continue
        alphas = _alpha_list(child)
        mods = {}
        for mod in child:
            mtag = _local(mod.tag)
            if mtag in ("shade", "tint", "lumMod", "lumOff", "satMod", "comp", "gray"):
                try:
                    mods[mtag] = _int(mod.attrib, "val") / 100000.0
                except (TypeError, ValueError):
                    pass
        if alphas:
            record["alpha"] = alphas[-1]
        if mods:
            record["modifiers"] = mods
        return record
    return None


def resolve_scheme_color(token: str, theme_ctx: dict[str, Any]) -> str | None:
    """Resolve a scheme colour token (accent1/tx1/bg2/...) to RGB via the master clrMap."""
    colors: dict[str, str] = theme_ctx.get("colors", {})
    mapping: dict[str, str] = theme_ctx.get("color_map", {})
    target = mapping.get(token, token)
    return colors.get(target) or colors.get(token)


def _fill_record(sp_pr: ET.Element | None, theme_ctx: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if sp_pr is None:
        return None
    for child in sp_pr:
        tag = _local(child.tag)
        if tag == "noFill":
            return {"type": "none"}
        if tag == "solidFill":
            record = {"type": "solid", "color": _color_record(child, theme_ctx)}
            if record["color"] and "alpha" in record["color"]:
                record["alpha"] = record["color"]["alpha"]
            return record
        if tag == "gradFill":
            stops = []
            for gs in child.findall("./a:gsLst/a:gs", NS):
                stop: dict[str, Any] = {"position": round(_int(gs.attrib, "pos") / 100000.0, 6)}
                color = _color_record(gs, theme_ctx)
                if color:
                    stop["color"] = color
                stops.append(stop)
            grad: dict[str, Any] = {"type": "gradient", "stops": stops}
            lin = child.find("./a:lin", NS)
            if lin is not None:
                grad["angle"] = round(_int(lin.attrib, "ang") / 60000.0, 4)
                grad["scaled"] = lin.get("scaled") == "1"
            path = child.find("./a:path", NS)
            if path is not None:
                grad["path"] = path.get("path")
                fill_to = path.find("./a:fillToRect", NS)
                if fill_to is not None:
                    grad["fill_to_rect"] = dict(fill_to.attrib)
            grad["rot_with_shape"] = child.get("rotWithShape") == "1"
            tile = child.find("./a:tileRect", NS)
            if tile is not None:
                grad["tile_rect"] = dict(tile.attrib)
            return grad
        if tag == "blipFill":
            blip = child.find("./a:blip", NS)
            return {
                "type": "picture",
                "relationship_id": blip.get(f"{{{R_NS}}}embed") if blip is not None else None,
                "alpha": (_alpha_list(blip) or [None])[-1] if blip is not None else None,
            }
        if tag == "pattFill":
            fg = _color_record(child.find("./a:fgClr", NS), theme_ctx)
            bg = _color_record(child.find("./a:bgClr", NS), theme_ctx)
            return {"type": "pattern", "pattern": child.get("prst"), "foreground": fg, "background": bg}
        if tag == "grpFill":
            return {"type": "group"}
    return None


def _line_record(ln: ET.Element | None, theme_ctx: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if ln is None:
        return None
    fill = _fill_record(ln, theme_ctx)
    record: dict[str, Any] = {}
    w = ln.get("w")
    if w is not None:
        record["width_emu"] = _int(ln.attrib, "w")
    if fill:
        record["fill"] = fill
    dash = ln.find("./a:prstDash", NS)
    if dash is not None:
        record["dash"] = dash.get("val")
    if ln.get("cap"):
        record["cap"] = ln.get("cap")
    for end_tag, key in (("a:headEnd", "start_arrow"), ("a:tailEnd", "end_arrow")):
        node = ln.find(f"./{end_tag}", NS)
        if node is not None:
            record[key] = {"type": node.get("type", "none"), "width": node.get("w"), "length": node.get("len")}
    return record or None


def _effect_record(sp_pr: ET.Element | None) -> list[dict[str, Any]] | None:
    if sp_pr is None:
        return None
    lst = sp_pr.find("./a:effectLst", NS)
    if lst is None:
        return None
    effects = []
    for node in lst:
        tag = _local(node.tag)
        item: dict[str, Any] = {"type": tag}
        for attr in ("blurRad", "dist", "dir", "sx", "sy", "kx", "ky", "algn"):
            if node.get(attr) is not None:
                item[attr] = node.get(attr)
        color = _color_record(node)
        if color:
            item["color"] = color
        effects.append(item)
    return effects or None


# --------------------------------------------------------------------------- #
# typography / text body
# --------------------------------------------------------------------------- #
def _body_pr_record(tx_body: ET.Element) -> dict[str, Any] | None:
    body_pr = tx_body.find("./a:bodyPr", NS)
    if body_pr is None:
        return None
    record: dict[str, Any] = {}
    for attr in ("wrap", "anchor", "anchorCtr", "vert", "rot", "spcFirstLastPara", "numCol", "compatLnSpc"):
        if body_pr.get(attr) is not None:
            record[attr] = body_pr.get(attr)
    for attr in ("lIns", "tIns", "rIns", "bIns"):
        if body_pr.get(attr) is not None:
            record[attr] = _int(body_pr.attrib, attr)
    autofit = None
    for child in body_pr:
        tag = _local(child.tag)
        if tag in ("spAutoFit", "noAutofit", "normAutofit"):
            autofit = {"type": tag}
            if tag == "normAutofit":
                if child.get("fontScale"):
                    autofit["font_scale"] = _int(child.attrib, "fontScale") / 100000.0
                if child.get("lnSpcReduction"):
                    autofit["line_reduction"] = _int(child.attrib, "lnSpcReduction") / 100000.0
            break
    if autofit:
        record["autofit"] = autofit
    return record


def _run_record(run: ET.Element, theme_ctx: dict[str, Any] | None) -> dict[str, Any]:
    r_pr = run.find("./a:rPr", NS)
    record: dict[str, Any] = {"text": "".join(t.text or "" for t in run.findall("./a:t", NS))}
    if r_pr is None:
        return record
    for attr, key in (("sz", "font_size_pt"), ("b", "bold"), ("i", "italic"), ("u", "underline"), ("strike", "strike"), ("spc", "character_spacing"), ("kern", "kerning"), ("baseline", "baseline"), ("lang", "language"), ("altLang", "alt_language")):
        value = r_pr.get(attr)
        if value is None:
            continue
        if attr == "sz":
            record[key] = _int(r_pr.attrib, "sz") / 100.0
        elif attr in ("spc", "kern", "baseline"):
            record[key] = _int(r_pr.attrib, attr)
        elif attr in ("b", "i"):
            record[key] = value == "1"
        else:
            record[key] = value
    for child in r_pr:
        tag = _local(child.tag)
        if tag == "latin":
            record["font_latin"] = child.get("typeface")
        elif tag == "ea":
            record["font_ea"] = child.get("typeface")
        elif tag == "cs":
            record["font_cs"] = child.get("typeface")
        elif tag == "sym":
            record["font_sym"] = child.get("typeface")
        elif tag == "solidFill":
            color = _color_record(child, theme_ctx)
            if color:
                record["color"] = color
    return record


def _paragraph_record(para: ET.Element, theme_ctx: dict[str, Any] | None) -> dict[str, Any]:
    record: dict[str, Any] = {}
    p_pr = para.find("./a:pPr", NS)
    if p_pr is not None:
        for attr, key in (("algn", "align"), ("lvl", "level")):
            if p_pr.get(attr) is not None:
                record[key] = p_pr.get(attr) if attr == "algn" else _int(p_pr.attrib, "lvl")
        ln_spc = p_pr.find("./a:lnSpc/a:spcPct", NS)
        if ln_spc is not None:
            record["line_spacing"] = _int(ln_spc.attrib, "val") / 100000.0
        for side, tag in (("space_before", "spcBef"), ("space_after", "spcAft")):
            node = p_pr.find(f"./a:{tag}/a:spcPts", NS)
            if node is not None:
                record[side] = _int(node.attrib, "val") / 100.0
    record["runs"] = [_run_record(run, theme_ctx) for run in para.findall("./a:r", NS)]
    fields = para.findall("./a:fld", NS)
    if fields:
        record["fields"] = ["".join(t.text or "" for t in f.findall("./a:t", NS)) for f in fields]
    return record


def _typography_record(tx_body: ET.Element | None, theme_ctx: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if tx_body is None:
        return None
    record: dict[str, Any] = {
        "body": _body_pr_record(tx_body),
        "paragraphs": [_paragraph_record(p, theme_ctx) for p in tx_body.findall("./a:p", NS)],
    }
    return record


def _text_content(tx_body: ET.Element | None) -> str:
    if tx_body is None:
        return ""
    return "\n".join(
        "".join(t.text or "" for t in p.findall(".//a:t", NS)) for p in tx_body.findall("./a:p", NS)
    )


# --------------------------------------------------------------------------- #
# custom geometry / tables / connectors
# --------------------------------------------------------------------------- #
def _cust_geom_record(cust_geom: ET.Element) -> dict[str, Any] | None:
    if cust_geom is None:
        return None
    record: dict[str, Any] = {}

    def _gd_list(path: str) -> list[dict[str, str]]:
        return [{"name": g.get("name") or "", "fmla": g.get("fmla") or ""} for g in cust_geom.findall(path, NS)]

    record["av"] = _gd_list("./a:avLst/a:gd")
    record["gd"] = _gd_list("./a:gdLst/a:gd")
    record["ah"] = _gd_list("./a:ahLst/a:gd")
    record["cxn"] = [dict(c.attrib) for c in cust_geom.findall("./a:cxnLst/a:cxn", NS)]
    rect = cust_geom.find("./a:rect", NS)
    record["rect"] = dict(rect.attrib) if rect is not None else None
    paths = []
    for path in cust_geom.findall("./a:pathLst/a:path", NS):
        commands = []
        for node in path:
            tag = _local(node.tag)
            if tag in ("moveTo", "lnTo", "cubicBezTo", "quadBezTo", "close", "arcTo"):
                commands.append(tag)
        paths.append({
            "w": _int(path.attrib, "w"),
            "h": _int(path.attrib, "h"),
            "fill": path.get("fill"),
            "command_counts": {t: commands.count(t) for t in sorted(set(commands))},
            "point_count": sum(1 for n in path if _local(n.tag) not in ("close",)),
        })
    record["paths"] = paths
    return record


def _table_record(frame: ET.Element, theme_ctx: dict[str, Any] | None = None) -> dict[str, Any] | None:
    tbl = frame.find("./a:graphic/a:graphicData/a:tbl", NS)
    if tbl is None:
        return None
    tbl_pr = tbl.find("./a:tblPr", NS)
    grid = []
    for col in tbl.findall("./a:tblGrid/a:gridCol", NS):
        grid.append(_int(col.attrib, "w"))
    rows = []
    for tr in tbl.findall("./a:tr", NS):
        cells = []
        for tc in tr.findall("./a:tc", NS):
            tc_pr = tc.find("./a:tcPr", NS)
            cell: dict[str, Any] = {
                "text": _text_content(tc.find("./a:txBody", NS)),
                "typography": _typography_record(tc.find("./a:txBody", NS), theme_ctx),
            }
            if tc_pr is not None:
                cell["fill"] = _fill_record(tc_pr, theme_ctx)
                cell["anchor"] = tc_pr.get("anchor")
                for attr in ("marL", "marR", "marT", "marB"):
                    if tc_pr.get(attr) is not None:
                        cell[attr] = _int(tc_pr.attrib, attr)
                borders = {}
                for edge in ("lnL", "lnR", "lnT", "lnB"):
                    border = _line_record(tc_pr.find(f"./a:{edge}", NS), theme_ctx)
                    if border:
                        borders[edge] = border
                if borders:
                    cell["borders"] = borders
                for attr in ("gridSpan", "rowSpan", "hMerge", "vMerge"):
                    if tc.get(attr) is not None:
                        cell[attr] = int(tc.get(attr)) if attr in ("gridSpan", "rowSpan") else tc.get(attr) == "1"
            cells.append(cell)
        rows.append({"height_emu": _int(tr.attrib, "h"), "cells": cells})
    flags = dict(tbl_pr.attrib) if tbl_pr is not None else {}
    return {"column_widths_emu": grid, "rows": rows, "flags": flags, "structure_hash": hashlib.sha256(ET.tostring(tbl, encoding="unicode").encode("utf-8")).hexdigest()[:16]}


def _connector_record(element: ET.Element, geom: dict[str, Any] | None) -> dict[str, Any] | None:
    sp_pr = element.find("./p:spPr", NS)
    if sp_pr is None:
        return None
    prst = sp_pr.find("./a:prstGeom", NS)
    record: dict[str, Any] = {
        "preset": prst.get("prst") if prst is not None else None,
    }
    ln = sp_pr.find("./a:ln", NS)
    line = _line_record(ln)
    if line:
        record["line"] = line
        for arrow in ("start_arrow", "end_arrow"):
            if arrow in line:
                record[arrow] = line[arrow]
    if geom:
        x, y, w, h = geom["x"], geom["y"], geom["cx"], geom["cy"]
        start = (x, y)
        end = (x + w, y + h)
        if geom.get("flip_h"):
            start = (x + w, y)
            end = (x, y + h)
        if geom.get("flip_v"):
            start = (start[0], y + h)
            end = (end[0], y)
        record["start"] = {"x": round(start[0], 2), "y": round(start[1], 2)}
        record["end"] = {"x": round(end[0], 2), "y": round(end[1], 2)}
    return record


# --------------------------------------------------------------------------- #
# media
# --------------------------------------------------------------------------- #
def _media_record(kind: str, element: ET.Element, rels: dict[str, str], resolver: Callable[[str], dict[str, Any] | None], theme_ctx: dict[str, Any]) -> dict[str, Any] | None:
    blip = element.find(".//a:blip", NS)
    if blip is None:
        return None
    rid = blip.get(f"{{{R_NS}}}embed")
    record: dict[str, Any] = {"relationship_id": rid}
    if rid:
        target = rels.get(rid)
        if target:
            record["target"] = target
            info = resolver(target)
            if info:
                record.update(info)
    src_rect = element.find(".//a:srcRect", NS)
    if src_rect is not None:
        crop_attrib = {k: _int(src_rect.attrib, k, 0) for k in ("l", "t", "r", "b") if src_rect.get(k) is not None}
        if crop_attrib:
            record["crop"] = crop_attrib
    stretch = element.find(".//a:stretch", NS)
    tile = element.find(".//a:tile", NS)
    if stretch is not None:
        record["stretch"] = True
    if tile is not None:
        record["tile"] = dict(tile.attrib)
    alphas = _alpha_list(blip)
    if alphas:
        record["alpha"] = alphas[-1]
    if kind == "pic":
        geom = _resolve_geometry(element, kind, [])
        if geom:
            record["rotation"] = geom["rotation"]
            record["flip_h"] = geom["flip_h"]
            record["flip_v"] = geom["flip_v"]
            record["rendered_bbox"] = geom["rendered_bbox"]
    return record


# --------------------------------------------------------------------------- #
# theme
# --------------------------------------------------------------------------- #
def _parse_theme(theme_xml: bytes | None) -> dict[str, Any]:
    if not theme_xml:
        return {"colors": {}, "color_map": {}, "fonts": {}}
    root = ET.fromstring(theme_xml)
    colors: dict[str, str] = {}
    scheme = root.find(".//a:clrScheme", NS)
    if scheme is not None:
        for node in scheme:
            name = _local(node.tag)
            srgb = node.find("./a:srgbClr", NS)
            sys = node.find("./a:sysClr", NS)
            if srgb is not None:
                colors[name] = (srgb.get("val") or "").upper()
            elif sys is not None:
                colors[name] = (sys.get("lastClr") or "").upper()
    fonts: dict[str, Any] = {}
    font_scheme = root.find(".//a:fontScheme", NS)
    if font_scheme is not None:
        for group, tag in (("major", "a:majorFont"), ("minor", "a:minorFont")):
            node = font_scheme.find(f"./{tag}", NS)
            if node is not None:
                entry: dict[str, Any] = {}
                for child in node:
                    ctag = _local(child.tag)
                    if ctag in ("latin", "ea", "cs"):
                        entry[ctag] = child.get("typeface")
                fonts[group] = entry
    return {"colors": colors, "color_map": {}, "fonts": fonts, "font_scheme": fonts}


def _clr_map(master_root: ET.Element | None) -> dict[str, str]:
    if master_root is None:
        return {}
    node = master_root.find("./p:clrMap", NS)
    return dict(node.attrib) if node is not None else {}


def _background_record(root: ET.Element | None, theme_ctx: dict[str, Any]) -> dict[str, Any] | None:
    if root is None:
        return None
    bg = root.find("./p:cSld/p:bg", NS)
    if bg is None:
        return None
    record: dict[str, Any] = {}
    bg_pr = bg.find("./p:bgPr", NS)
    bg_ref = bg.find("./p:bgRef", NS)
    if bg_pr is not None:
        record["fill"] = _fill_record(bg_pr, theme_ctx)
        record["shade_to_title"] = bg_pr.find("./a:effectLst", NS) is not None
    elif bg_ref is not None:
        record["reference_index"] = _int(bg_ref.attrib, "idx")
        record["color"] = _color_record(bg_ref, theme_ctx)
    return record or None


# --------------------------------------------------------------------------- #
# page kind (stdlib mirror of page_dna.classify_page_kind)
# --------------------------------------------------------------------------- #
_TOC_TEXT = re.compile(r"目\s*录|contents|agenda", re.IGNORECASE)
_LAYOUT_TOKENS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cover", ("封面", "cover", "title slide")),
    ("toc", ("目录", "contents", "toc")),
    ("closing", ("结束", "致谢", "thank", "closing", "end")),
    ("section", ("章节", "section", "divider", "过渡")),
    ("content", ("内容", "content", "正文", "body")),
)


_BAND_PRSTS = ("rect", "roundRect", "round2SameRect")
_BAND_MIN_EMU = 2 * 914400  # page_dna: >= 2in declared in both axes


def _has_rotated_band(shapes: list[dict[str, Any]]) -> bool:
    """Mirror page_dna.page_signals: a large rotated rectangular band."""
    for shape in shapes:
        geometry = shape.get("geometry_emu") or {}
        if abs(float(geometry.get("rotation") or 0.0)) <= 1.0:
            continue
        prst = (shape.get("preset_geometry") or {}).get("prst")
        if prst not in _BAND_PRSTS:
            continue
        if geometry.get("cx", 0) >= _BAND_MIN_EMU and geometry.get("cy", 0) >= _BAND_MIN_EMU:
            return True
    return False


def classify_page_kind_xml(
    *,
    slide_texts: str,
    layout_name: str | None,
    index: int,
    total: int,
    slide_shape_count: int,
    has_band: bool,
    layout_shape_count: int,
) -> str:
    """Position → headline text → layout name → structure, mirroring page_dna."""
    if total <= 1:
        # a one-page deck is only a cover when its headline is not a TOC
        return "toc" if (slide_texts and _TOC_TEXT.search(slide_texts)) else "cover"
    if index == 1:
        return "cover"
    if index == total:
        return "closing"
    if slide_texts and _TOC_TEXT.search(slide_texts):
        return "toc"
    name = (layout_name or "").strip().lower()
    if name and name != "blank":
        for kind, tokens in _LAYOUT_TOKENS:
            if any(token in name for token in tokens):
                return kind
    if has_band:
        return "section"
    if slide_shape_count == 0 and layout_shape_count <= 2 and index != total:
        return "section"
    return "content"


def _toc_structure(root: ET.Element, rels: dict[str, str], resolver: Callable[[str], dict[str, Any] | None]) -> dict[str, Any] | None:
    """Structured TOC extraction: title, items, numbering, geometry."""
    sp_tree = root.find(".//p:spTree", NS)
    if sp_tree is None:
        return None
    title = ""
    items: list[dict[str, Any]] = []
    indicators = 0
    for element in sp_tree:
        kind = _local(element.tag)
        if kind not in _SHAPE_KINDS:
            continue
        c_nv = element.find(_NV_PATHS.get(kind, "./p:nvSpPr/p:cNvPr"), NS)
        name = (c_nv.get("name") or "").lower() if c_nv is not None else ""
        ph = element.find("./p:nvSpPr/p:nvPr/p:ph", NS)
        ph_type = ph.get("type") if ph is not None else None
        text = _text_content(element.find("./p:txBody", NS)).strip()
        geom = _resolve_geometry(element, kind, [])
        if ph_type in ("title", "ctrTitle") or "title" in name:
            title = text
            continue
        if not text:
            if kind in ("pic", "sp"):
                indicators += 1
            continue
        # a free-standing shape whose headline reads 目录/CONTENTS is the title
        if not title and _TOC_TEXT.search(text):
            title = text
            continue
        lines = [line for line in text.splitlines() if line.strip()]
        for line in lines:
            numbering = None
            match = re.match(r"^\s*(\d{1,2})[\.\、\)\）]?\s*(.+)$", line)
            if match:
                numbering = int(match.group(1))
                line = match.group(2)
            items.append({
                "text": line.strip(),
                "numbering": numbering,
                "level": (geom or {}).get("y", 0),
                "geometry_emu": {k: geom[k] for k in ("x", "y", "cx", "cy") if geom and k in geom},
            })
    if not title and not items:
        return None
    numbers = [item["numbering"] for item in items if item["numbering"] is not None]
    return {
        "title": title,
        "items": items,
        "item_count": len(items),
        "numbering": "arabic" if numbers else ("none" if items else None),
        "numbering_ordered": numbers == sorted(numbers) if numbers else None,
        "indicator_count": indicators,
        "structure_fingerprint": hashlib.sha256(
            json.dumps([title, indicators, [[i["text"], i["numbering"], i.get("geometry_emu")] for i in items]], ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16],
    }


# --------------------------------------------------------------------------- #
# shape extraction
# --------------------------------------------------------------------------- #
def _shape_record(
    element: ET.Element,
    z_index: int,
    rels: dict[str, str],
    theme_ctx: dict[str, Any],
    resolver: Callable[[str], dict[str, Any] | None],
    ancestors: list[dict[str, Any]],
    parent_id: str | None = None,
) -> dict[str, Any] | None:
    kind = _local(element.tag)
    if kind not in _SHAPE_KINDS:
        return None

    c_nv = element.find(_NV_PATHS[kind], NS)
    shape_id = c_nv.get("id") if c_nv is not None else None
    name = c_nv.get("name") if c_nv is not None else None
    geom = _resolve_geometry(element, kind, ancestors)

    record: dict[str, Any] = {
        "z_index": z_index,
        "parent_id": parent_id,
        "shape_id": shape_id,
        "name": name,
        "kind": kind,
        "geometry_emu": geom,
        "relationship_id": None,
        "target": None,
        "raw_xml": ET.tostring(element, encoding="unicode"),
    }

    sp_pr = element.find("./p:spPr", NS)
    if sp_pr is not None:
        record["spPr_xml"] = ET.tostring(sp_pr, encoding="unicode")
        cust_geom = sp_pr.find("./a:custGeom", NS)
        if cust_geom is not None:
            record["custom_geometry_xml"] = ET.tostring(cust_geom, encoding="unicode")

    fill = _fill_record(sp_pr, theme_ctx)
    if fill is not None:
        record["fill"] = fill
    line = _line_record(sp_pr.find("./a:ln", NS) if sp_pr is not None else None, theme_ctx)
    if line is not None:
        record["line"] = line
    effects = _effect_record(sp_pr)
    if effects:
        record["effects"] = effects

    cust_geom = sp_pr.find("./a:custGeom", NS) if sp_pr is not None else None
    if cust_geom is not None:
        record["custom_geometry"] = _cust_geom_record(cust_geom)
    prst_geom = sp_pr.find("./a:prstGeom", NS) if sp_pr is not None else None
    if prst_geom is not None:
        av = prst_geom.find("./a:avLst", NS)
        record["preset_geometry"] = {
            "prst": prst_geom.get("prst"),
            "adjustments": [dict(g.attrib) for g in av.findall("./a:gd", NS)] if av is not None else [],
        }

    ph = element.find("./p:nvSpPr/p:nvPr/p:ph", NS)
    if ph is None:
        ph = element.find(".//p:nvPr/p:ph", NS)
    if ph is not None:
        record["placeholder"] = dict(ph.attrib)

    tx_body = element.find("./p:txBody", NS)
    if tx_body is not None:
        record["text_body_xml"] = ET.tostring(tx_body, encoding="unicode")
        typography = _typography_record(tx_body, theme_ctx)
        if typography:
            record["typography"] = typography
        record["text"] = _text_content(tx_body)

    media = _media_record(kind, element, rels, resolver, theme_ctx)
    if media:
        record["media"] = media
        if media.get("relationship_id"):
            record["relationship_id"] = media["relationship_id"]
            record["target"] = media.get("target")

    if kind == "cxnSp":
        connector = _connector_record(element, geom)
        if connector:
            record["connector"] = connector

    if kind == "graphicFrame":
        table = _table_record(element, theme_ctx)
        if table:
            record["table"] = table

    if kind == "grpSp":
        group_xfrm = geom
        child_ancestors = ancestors + [group_xfrm] if group_xfrm else ancestors
        children = []
        for child_index, child in enumerate(list(element)):
            child_record = _shape_record(child, child_index, rels, theme_ctx, resolver, child_ancestors, shape_id)
            if child_record is not None:
                children.append(child_record)
        record["children"] = children

    return record


def _shape_records(
    root: ET.Element,
    rels: dict[str, str],
    theme_ctx: dict[str, Any],
    resolver: Callable[[str], dict[str, Any] | None],
) -> list[dict[str, Any]]:
    sp_tree = root.find(".//p:spTree", NS)
    if sp_tree is None:
        return []
    records = []
    for index, element in enumerate(list(sp_tree)):
        record = _shape_record(element, index, rels, theme_ctx, resolver, [])
        if record is not None:
            records.append(record)
    return records


# --------------------------------------------------------------------------- #
# placeholder inheritance resolution
# --------------------------------------------------------------------------- #
def _placeholder_key(ph: dict[str, Any] | None) -> tuple[str, str]:
    if not ph:
        return ("", "")
    return (ph.get("type") or "", ph.get("idx") or "")


def _style_of_shape(shape: dict[str, Any]) -> dict[str, Any]:
    """First-run effective style of a shape (or defRPr summary)."""
    typography = shape.get("typography") or {}
    for para in typography.get("paragraphs", []):
        for run in para.get("runs", []):
            style: dict[str, Any] = {}
            if "font_size_pt" in run:
                style["font_size_pt"] = run["font_size_pt"]
            if "bold" in run:
                style["bold"] = run["bold"]
            if "font_latin" in run:
                style["typeface"] = run["font_latin"]
            color = run.get("color") or {}
            if color.get("rgb"):
                style["color_rgb"] = color["rgb"]
            elif color.get("scheme"):
                style["color_scheme"] = color["scheme"]
                if color.get("resolved_rgb"):
                    style["color_rgb"] = color["resolved_rgb"]
            if style:
                return style
    return {}


def _parse_txstyles(master_root: ET.Element | None) -> dict[str, dict[str, Any]]:
    """Master text styles: titleStyle/bodyStyle/otherStyle lvl1 defRPr, as style dicts."""
    styles: dict[str, dict[str, Any]] = {}
    tx_styles = master_root.find("./p:txStyles", NS) if master_root is not None else None
    if tx_styles is None:
        return styles
    for name in ("titleStyle", "bodyStyle", "otherStyle"):
        node = tx_styles.find(f"./p:{name}", NS)
        if node is None:
            continue
        def_rpr = node.find("./a:lvl1pPr/a:defRPr", NS)
        if def_rpr is None:
            continue
        style: dict[str, Any] = {}
        if def_rpr.get("sz"):
            style["font_size_pt"] = _int(def_rpr.attrib, "sz") / 100.0
        if def_rpr.get("b"):
            style["bold"] = def_rpr.get("b") == "1"
        latin = def_rpr.find("./a:latin", NS)
        if latin is not None:
            style["typeface"] = latin.get("typeface")
        color = _color_record(def_rpr.find("./a:solidFill", NS))
        if color:
            if color.get("rgb"):
                style["color_rgb"] = color["rgb"]
            elif color.get("scheme"):
                style["color_scheme"] = color["scheme"]
        styles[name] = style
    return styles


def _txstyle_for(ph: dict[str, Any], txstyles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ph_type = (ph.get("type") or "").lower()
    if ph_type in ("title", "ctrtitle"):
        return txstyles.get("titleStyle", {})
    if ph_type == "body" or ph.get("idx"):
        return txstyles.get("bodyStyle", {})
    return txstyles.get("otherStyle", {})


def _resolve_placeholder_style(
    slide_shape: dict[str, Any],
    layout_shapes: list[dict[str, Any]],
    master_shapes: list[dict[str, Any]],
    txstyles: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """declared / inherited / resolved / source chain for placeholder text style."""
    ph = slide_shape.get("placeholder")
    if not ph:
        return None
    key = _placeholder_key(ph)

    def _find(shapes: list[dict[str, Any]]) -> dict[str, Any] | None:
        for shape in shapes:
            if _placeholder_key(shape.get("placeholder")) == key:
                return shape
        # type-alias fallback for placeholders that omit idx (ctrTitle -> title)
        alias = {"ctrtitle": "title", "subtitle": "body"}.get(key[0].lower(), key[0].lower())
        for shape in shapes:
            candidate = _placeholder_key(shape.get("placeholder"))
            if candidate[0].lower() == alias:
                return shape
        return None

    layout_shape = _find(layout_shapes)
    master_shape = _find(master_shapes)
    declared = _style_of_shape(slide_shape)
    inherited_layout = _style_of_shape(layout_shape) if layout_shape else {}
    inherited_master = _style_of_shape(master_shape) if master_shape else {}
    master_style = _txstyle_for(ph, txstyles or {})

    resolved: dict[str, Any] = {}
    source: dict[str, Any] = {}
    for prop in ("font_size_pt", "bold", "typeface", "color_rgb", "color_scheme"):
        if prop in declared:
            resolved[prop] = declared[prop]
            source[prop] = "slide"
        elif prop in inherited_layout:
            resolved[prop] = inherited_layout[prop]
            source[prop] = "layout"
        elif prop in inherited_master:
            resolved[prop] = inherited_master[prop]
            source[prop] = "master"
        elif prop in master_style:
            resolved[prop] = master_style[prop]
            source[prop] = "master"
    if not resolved:
        return None
    return {
        "placeholder": ph,
        "layout_shape_id": (layout_shape or {}).get("shape_id"),
        "master_shape_id": (master_shape or {}).get("shape_id"),
        "declared": declared or None,
        "inherited": {"layout": inherited_layout or None, "master": inherited_master or None},
        "resolved": resolved,
        "source": source,
    }


# --------------------------------------------------------------------------- #
# media asset resolver
# --------------------------------------------------------------------------- #
def _make_asset_resolver(zf: zipfile.ZipFile, rels: dict[str, str], base_dir: str) -> Callable[[str], dict[str, Any] | None]:
    cache: dict[str, dict[str, Any] | None] = {}

    def resolver(target: str | None) -> dict[str, Any] | None:
        if not target:
            return None
        if target in cache:
            return cache[target]
        path = _zip_path(base_dir, target)
        try:
            blob = zf.read(path)
        except KeyError:
            cache[target] = None
            return None
        info = {
            "package_path": path,
            "sha256": hashlib.sha256(blob).hexdigest(),
            "byte_size": len(blob),
            "content_type": "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png" if path.lower().endswith(".png") else None,
        }
        cache[target] = info
        return info

    return resolver


def _media_manifest(zf: zipfile.ZipFile, rel_sets: list[tuple[str, dict[str, str]]]) -> dict[str, Any]:
    manifest: dict[str, Any] = {}
    for base_dir, rels in rel_sets:
        for relationship_id, target in rels.items():
            if not target or "media/" not in target:
                continue
            path = _zip_path(base_dir, target)
            if path not in zf.namelist():
                continue
            blob = zf.read(path)
            item = manifest.setdefault(
                path,
                {
                    "sha256": hashlib.sha256(blob).hexdigest(),
                    "size": len(blob),
                    "relationship_ids": [],
                },
            )
            item["relationship_ids"].append(relationship_id)
    return manifest


def _slide_role(index: int, count: int) -> str:
    if index == 1:
        return "first"
    if index == count:
        return "last"
    return "body"


# --------------------------------------------------------------------------- #
# main extraction
# --------------------------------------------------------------------------- #
def _raw_xml(zf: zipfile.ZipFile, path: str | None) -> str | None:
    if not path:
        return None
    try:
        return zf.read(path).decode("utf-8")
    except (KeyError, UnicodeDecodeError):
        return None


def _slide_texts(root: ET.Element) -> str:
    return "\n".join((t.text or "") for t in root.findall(".//a:t", NS))


def extract_fidelity_dna(path: str | Path, slide_index: int = 1) -> dict[str, Any]:
    """Extract the hardened OOXML fidelity layer for one slide.

    Returns schema ``template-dna/fidelity/v2``: everything v1 exposed, plus
    page kind, structured styles/typography/tables/connectors, group-resolved
    transforms with rendered bboxes, theme resolution, placeholder inheritance
    chains and the Master→Layout→Slide global render order.
    """
    source = Path(path)
    if slide_index < 1:
        raise ValueError("slide_index is 1-based and must be >= 1")

    with zipfile.ZipFile(source) as zf:
        presentation_xml = ET.fromstring(zf.read("ppt/presentation.xml"))
        slide_paths = sorted(
            [n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)],
            key=lambda n: int(re.search(r"(\d+)", n).group(1)),
        )
        if slide_index > len(slide_paths):
            raise ValueError(f"slide_index {slide_index} exceeds {len(slide_paths)} slides")

        slide_path = slide_paths[slide_index - 1]
        slide_root = ET.fromstring(zf.read(slide_path))
        slide_rels_path = posixpath.join("ppt/slides/_rels", posixpath.basename(slide_path) + ".rels")
        slide_rels_xml = zf.read(slide_rels_path)
        slide_rels = _rel_map(slide_rels_xml)
        layout_target = slide_rels.get(next((k for k, v in slide_rels.items() if v and "slideLayout" in v), ""))
        layout_path = _zip_path("ppt/slides", layout_target) if layout_target else None
        if not layout_path or layout_path not in zf.namelist():
            raise ValueError("slide layout relationship could not be resolved")

        layout_root = ET.fromstring(zf.read(layout_path))
        layout_dir = posixpath.dirname(layout_path)
        layout_rels_path = posixpath.join(layout_dir, "_rels", posixpath.basename(layout_path) + ".rels")
        layout_rels_xml = zf.read(layout_rels_path)
        layout_rels = _rel_map(layout_rels_xml)

        master_target = layout_rels.get(next((k for k, v in layout_rels.items() if v and "slideMaster" in v), ""))
        master_path = _zip_path(layout_dir, master_target) if master_target else None
        master_root = ET.fromstring(zf.read(master_path)) if master_path and master_path in zf.namelist() else None
        master_rels_path = (
            posixpath.join(posixpath.dirname(master_path), "_rels", posixpath.basename(master_path) + ".rels")
            if master_path
            else None
        )
        master_rels_xml = zf.read(master_rels_path) if master_rels_path and master_rels_path in zf.namelist() else b""
        master_rels = _rel_map(master_rels_xml) if master_rels_xml else {}

        theme_paths = [n for n in zf.namelist() if re.fullmatch(r"ppt/theme/theme\d+\.xml", n)]
        theme_path = theme_paths[0] if theme_paths else None
        theme_xml = zf.read(theme_path) if theme_path else None
        theme_parsed = _parse_theme(theme_xml)
        theme_ctx: dict[str, Any] = {
            "colors": theme_parsed["colors"],
            "color_map": _clr_map(master_root),
        }

        slide_count = len(slide_paths)
        slide_resolver = _make_asset_resolver(zf, slide_rels, posixpath.dirname(slide_path))
        layout_resolver = _make_asset_resolver(zf, layout_rels, layout_dir)
        master_resolver = _make_asset_resolver(zf, master_rels, posixpath.dirname(master_path) if master_path else "")

        master_shapes = _shape_records(master_root, master_rels, theme_ctx, master_resolver) if master_root is not None else []
        layout_shapes = _shape_records(layout_root, layout_rels, theme_ctx, layout_resolver)
        slide_shapes = _shape_records(slide_root, slide_rels, theme_ctx, slide_resolver)

        master_count = len(master_shapes)
        layout_count = len(layout_shapes)
        for offset, shape in enumerate(slide_shapes):
            shape["global_render_order"] = master_count + layout_count + offset
        for offset, shape in enumerate(layout_shapes):
            shape["global_render_order"] = master_count + offset
        for offset, shape in enumerate(master_shapes):
            shape["global_render_order"] = offset
        total_layers = master_count + layout_count + len(slide_shapes)
        for shape in (*master_shapes, *layout_shapes, *slide_shapes):
            order = shape["global_render_order"]
            shape["stack"] = {"source_z": shape["z_index"], "global_z": order, "below": order, "above": total_layers - 1 - order}

        layout_name_el = layout_root.find("./p:cSld", NS)
        layout_name = layout_name_el.get("name") if layout_name_el is not None else None
        page_kind = classify_page_kind_xml(
            slide_texts=_slide_texts(slide_root),
            layout_name=layout_name,
            index=slide_index,
            total=slide_count,
            slide_shape_count=len(slide_shapes),
            has_band=_has_rotated_band(slide_shapes) or _has_rotated_band(layout_shapes),
            layout_shape_count=layout_count,
        )

        toc = _toc_structure(slide_root, slide_rels, slide_resolver) if page_kind == "toc" else None

        background_sources = []
        for label, root in (("slide", slide_root), ("layout", layout_root), ("master", master_root)):
            bg = _background_record(root, theme_ctx)
            if bg:
                bg = dict(bg)
                bg["source"] = label
                background_sources.append(bg)

        placeholder_resolutions = []
        txstyles = _parse_txstyles(master_root)
        for shape in slide_shapes:
            resolution = _resolve_placeholder_style(shape, layout_shapes, master_shapes, txstyles)
            if resolution:
                placeholder_resolutions.append({"shape_id": shape["shape_id"], **resolution})

        return {
            "schema": SCHEMA,
            "source": str(source),
            "slide_index": slide_index,
            "surface_role": _slide_role(slide_index, slide_count),
            "page_kind": page_kind,
            "toc": toc,
            "presentation": {
                "slide_count": slide_count,
                "slide_size_emu": {
                    "width": int(presentation_xml.find("./p:sldSz", NS).get("cx")),
                    "height": int(presentation_xml.find("./p:sldSz", NS).get("cy")),
                },
            },
            "theme": {
                "path": theme_path,
                "raw_xml": _raw_xml(zf, theme_path) if theme_path else None,
                "colors": theme_parsed["colors"],
                "fonts": theme_parsed["fonts"],
                "color_map": theme_ctx["color_map"],
            },
            "master": {
                "path": master_path,
                "raw_xml": _raw_xml(zf, master_path) if master_path else None,
                "relationships_xml": master_rels_xml.decode("utf-8") if master_rels_xml else None,
                "background": _background_record(master_root, theme_ctx),
                "shapes": master_shapes,
            },
            "layout": {
                "path": layout_path,
                "name": layout_name,
                "raw_xml": _raw_xml(zf, layout_path),
                "relationships_xml": layout_rels_xml.decode("utf-8"),
                "background": _background_record(layout_root, theme_ctx),
                "shapes": layout_shapes,
            },
            "slide": {
                "path": slide_path,
                "raw_xml": _raw_xml(zf, slide_path),
                "relationships_xml": slide_rels_xml.decode("utf-8"),
                "background": _background_record(slide_root, theme_ctx),
                "background_resolved": background_sources,
                "shapes": slide_shapes,
            },
            "placeholder_resolutions": placeholder_resolutions,
            "assets": _media_manifest(
                zf,
                [
                    (layout_dir, layout_rels),
                    (posixpath.dirname(slide_path), slide_rels),
                    (posixpath.dirname(master_path), master_rels) if master_path else ("", {}),
                ],
            ),
        }


def export_fidelity_dna(path: str | Path, out_dir: str | Path, slide_index: int = 1) -> Path:
    """Write fidelity DNA JSON and referenced media assets into a workspace."""
    source = Path(path)
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    dna = extract_fidelity_dna(source, slide_index=slide_index)
    (destination / "dna.json").write_text(
        json.dumps(dna, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with zipfile.ZipFile(source) as zf:
        assets_dir = destination / "assets"
        assets_dir.mkdir(exist_ok=True)
        for package_path in dna["assets"]:
            target = assets_dir / Path(package_path).name
            target.write_bytes(zf.read(package_path))
    return destination / "dna.json"
