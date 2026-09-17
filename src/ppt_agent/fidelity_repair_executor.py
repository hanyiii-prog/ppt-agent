"""Repair Executor: apply property-level repair directives to a real PPTX.

The executor mutates the *minimum* OOXML property each directive names — a
position fix writes one ``x`` attribute, an alpha fix writes one ``<a:alpha>``
child — and never deletes/rebuilds a shape for a property-level difference.
Structural directives that cannot be expressed as a minimal property edit
(added/removed layers, page-kind changes, media asset swaps) are explicitly
reported as ``skipped`` so the caller can escalate instead of silently
pretending the repair happened.

Directives address elements by their OOXML ``cNvPr`` id (``slide.shapes[id=7].
geometry.x``), so pairing corrections (reorders) can never redirect an edit to
the wrong shape. Layer-order repairs are collected per container and applied as
one deterministic spTree rebuild. Shape addressing therefore agrees with the
extractor, whose ``z_index`` is the spTree child index.

Implementation is stdlib-only: the package is rewritten at the zip entry level
and affected XML parts are re-serialized with ElementTree.
"""
from __future__ import annotations

import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .fidelity import A_NS, NS, _NV_PATHS, _SHAPE_KINDS, _local, extract_fidelity_dna
from .fidelity_diff import FidelityReport, compare_dna

_PATH_RE = re.compile(r"^(slide|master|layout)\.shapes\[id=([^\]]+)\](?:\.children\[(\d+)\])?\.?(.*)$")
_ZPATH_RE = re.compile(r"^(slide|master|layout)\.shapes\[z(\d+)\]\.?(.*)$")


# --------------------------------------------------------------------------- #
# package plumbing
# --------------------------------------------------------------------------- #
def _rel_map(xml_bytes: bytes) -> dict[str, str]:
    root = ET.fromstring(xml_bytes)
    return {node.get("Id"): node.get("Target") for node in root if node.get("Id")}


def _zip_path(base_dir: str, target: str) -> str:
    return posixpath.normpath(posixpath.join(base_dir, target)).lstrip("/")


def _locate_parts(zf: zipfile.ZipFile, slide_index: int = 1) -> dict[str, str]:
    """slide/master/layout part paths for one slide, via the relationship chain."""
    slide_paths = sorted(
        [n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)],
        key=lambda n: int(re.search(r"(\d+)", n).group(1)),
    )
    if slide_index > len(slide_paths):
        raise ValueError(f"slide_index {slide_index} exceeds {len(slide_paths)} slides")
    slide_path = slide_paths[slide_index - 1]
    slide_rels_path = posixpath.join("ppt/slides/_rels", posixpath.basename(slide_path) + ".rels")
    slide_rels = _rel_map(zf.read(slide_rels_path))
    layout_target = slide_rels.get(next((k for k, v in slide_rels.items() if v and "slideLayout" in v), ""))
    layout_path = _zip_path("ppt/slides", layout_target) if layout_target else None

    master_path = None
    if layout_path and layout_path in zf.namelist():
        layout_dir = posixpath.dirname(layout_path)
        layout_rels_path = posixpath.join(layout_dir, "_rels", posixpath.basename(layout_path) + ".rels")
        layout_rels = _rel_map(zf.read(layout_rels_path))
        master_target = layout_rels.get(next((k for k, v in layout_rels.items() if v and "slideMaster" in v), ""))
        master_path = _zip_path(layout_dir, master_target) if master_target else None

    return {"slide": slide_path, "layout": layout_path or "", "master": master_path or ""}


def _write_zip(source: Path, entries: dict[str, bytes], output: Path) -> None:
    with zipfile.ZipFile(source) as zin:
        names = zin.namelist()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            zout.writestr(name, entries[name])


def _sp_tree(root: ET.Element) -> ET.Element:
    sp_tree = root.find(".//p:spTree", NS)
    if sp_tree is None:
        raise ValueError("package part has no spTree")
    return sp_tree


def _shape_id(element: ET.Element) -> str | None:
    kind = _local(element.tag)
    nv_path = _NV_PATHS.get(kind)
    if not nv_path:
        return None
    nv = element.find(nv_path, NS)
    return nv.get("id") if nv is not None else None


def _find_by_id(root: ET.Element, shape_id: str) -> ET.Element:
    for element in root.iter():
        if _local(element.tag) not in _SHAPE_KINDS:
            continue
        if _shape_id(element) == str(shape_id):
            return element
    raise KeyError(f"shape id {shape_id} not found in part")


def _ensure_xfrm(element: ET.Element) -> ET.Element:
    # graphicFrame keeps its xfrm at p:xfrm; every other shape nests it in spPr
    kind = _local(element.tag)
    if kind == "graphicFrame":
        xfrm = element.find("./p:xfrm", NS)
        if xfrm is None:
            raise ValueError("graphicFrame has no xfrm")
        return xfrm
    sp_pr = element.find("./p:spPr", NS)
    if sp_pr is None:
        raise ValueError("shape has no spPr")
    xfrm = sp_pr.find("./a:xfrm", NS)
    if xfrm is None:
        raise ValueError("shape has no xfrm")
    return xfrm


def _ensure_parent(element: ET.Element, path: str) -> ET.Element:
    node = element.find(path, NS)
    if node is None:
        raise ValueError(f"required element {path} missing")
    return node


# --------------------------------------------------------------------------- #
# property handlers (minimal edits only)
# --------------------------------------------------------------------------- #
def _set_attr(node: ET.Element, name: str, value: Any) -> None:
    if value is None:
        node.attrib.pop(name, None)
    else:
        node.set(name, str(value))


def _apply_geometry(element: ET.Element, prop: str, value: Any) -> None:
    xfrm = _ensure_xfrm(element)
    if prop in ("x", "y"):
        off = _ensure_parent(xfrm, "./a:off")
        _set_attr(off, prop, None if value is None else int(round(float(value))))
    elif prop in ("cx", "cy", "w", "h"):
        ext = _ensure_parent(xfrm, "./a:ext")
        attr = "cx" if prop in ("cx", "w") else "cy"
        _set_attr(ext, attr, None if value is None else int(round(float(value))))
    elif prop == "rotation":
        if value is None:
            _set_attr(xfrm, "rot", None)
        else:
            xfrm.set("rot", str(int(round((float(value) % 360.0) * 60000.0))))
    elif prop == "flip_h":
        _set_attr(xfrm, "flipH", None if value is None else ("1" if value else None))
    elif prop == "flip_v":
        _set_attr(xfrm, "flipV", None if value is None else ("1" if value else None))
    else:
        raise ValueError(f"unsupported geometry property: {prop}")


def _solid_srgb(element: ET.Element) -> ET.Element | None:
    sp_pr = element.find("./p:spPr", NS)
    if sp_pr is None:
        return None
    solid = sp_pr.find("./a:solidFill", NS)
    if solid is None:
        return None
    return solid.find("./a:srgbClr", NS)


def _set_alpha_on_color(color: ET.Element, alpha: float) -> None:
    for existing in color.findall("./a:alpha", NS):
        color.remove(existing)
    alpha_node = color.makeelement(f"{{{A_NS}}}alpha", {"val": str(int(round(float(alpha) * 100000)))})
    color.append(alpha_node)


def _apply_fill(element: ET.Element, prop_path: str, value: Any) -> None:
    if prop_path.endswith("alpha"):
        color = _solid_srgb(element)
        if color is None:
            raise ValueError("no solid srgbClr fill to repair alpha on")
        _set_alpha_on_color(color, value)
        return
    if prop_path.endswith("color.rgb"):
        color = _solid_srgb(element)
        if color is None:
            raise ValueError("no solid srgbClr fill to repair color on")
        _set_attr(color, "val", None if value is None else str(value).upper())
        return
    if prop_path.endswith("angle"):
        sp_pr = element.find("./p:spPr", NS)
        grad = sp_pr.find("./a:gradFill", NS) if sp_pr is not None else None
        lin = grad.find("./a:lin", NS) if grad is not None else None
        if lin is None:
            raise ValueError("no gradient lin element to repair angle on")
        _set_attr(lin, "ang", None if value is None else int(round((float(value) % 360.0) * 60000.0)))
        return
    raise ValueError(f"unsupported fill property: {prop_path}")


def _apply_line(element: ET.Element, prop_path: str, value: Any) -> None:
    sp_pr = element.find("./p:spPr", NS)
    ln = sp_pr.find("./a:ln", NS) if sp_pr is not None else None
    if ln is None:
        raise ValueError("no a:ln to repair")
    if prop_path.endswith("width_emu"):
        _set_attr(ln, "w", None if value is None else int(round(float(value))))
        return
    if prop_path.endswith("color.rgb"):
        solid = ln.find("./a:solidFill", NS)
        color = solid.find("./a:srgbClr", NS) if solid is not None else None
        if color is None:
            raise ValueError("no line srgbClr to repair")
        _set_attr(color, "val", None if value is None else str(value).upper())
        return
    if prop_path.endswith("dash"):
        dash = ln.find("./a:prstDash", NS)
        if dash is None:
            dash = ln.makeelement(f"{{{A_NS}}}prstDash", {})
            ln.append(dash)
        _set_attr(dash, "val", value)
        return
    raise ValueError(f"unsupported line property: {prop_path}")


def _apply_crop(element: ET.Element, prop_path: str, value: Any) -> None:
    # pictures carry p:blipFill; shape picture-fills carry a:blipFill in spPr
    blip_fill = element.find(".//p:blipFill", NS)
    if blip_fill is None:
        blip_fill = element.find(".//a:blipFill", NS)
    if blip_fill is None:
        raise ValueError("no blipFill to repair crop on")
    src_rect = blip_fill.find("./a:srcRect", NS)
    attr = prop_path.rsplit(".", 1)[-1]
    if attr not in ("l", "t", "r", "b"):
        raise ValueError(f"unsupported crop attribute: {attr}")
    if src_rect is None:
        if value is None:
            return
        blip = blip_fill.find("./a:blip", NS)
        src_rect = blip_fill.makeelement(f"{{{A_NS}}}srcRect", {})
        blip_fill.insert(list(blip_fill).index(blip) + 1 if blip is not None else 0, src_rect)
    _set_attr(src_rect, attr, None if value is None else int(round(float(value))))
    if not src_rect.attrib:
        blip_fill.remove(src_rect)


def _apply_typography(element: ET.Element, prop_path: str, value: Any) -> None:
    body = element.find("./p:txBody", NS)
    if body is None:
        raise ValueError("no txBody to repair")
    if prop_path.startswith("body."):
        body_pr = _ensure_parent(body, "./a:bodyPr")
        attr = prop_path.split(".", 2)[2]
        _set_attr(body_pr, attr, None if value is None else int(round(float(value))))
        return
    match = re.match(r"paragraphs\[(\d+)\]\.runs\[(\d+)\]\.(.+)", prop_path)
    if not match:
        raise ValueError(f"unsupported typography property: {prop_path}")
    para_index, run_index, run_prop = int(match.group(1)), int(match.group(2)), match.group(3)
    paras = body.findall("./a:p", NS)
    if para_index >= len(paras):
        raise IndexError("paragraph index out of range")
    runs = paras[para_index].findall("./a:r", NS)
    if run_index >= len(runs):
        raise IndexError("run index out of range")
    r_pr = runs[run_index].find("./a:rPr", NS)
    if r_pr is None:
        r_pr = runs[run_index].makeelement(f"{{{A_NS}}}rPr", {"lang": "en-US"})
        runs[run_index].insert(0, r_pr)
    if run_prop == "font_size_pt":
        _set_attr(r_pr, "sz", None if value is None else int(round(float(value) * 100.0)))
    elif run_prop == "bold":
        _set_attr(r_pr, "b", None if value is None else ("1" if value else "0"))
    elif run_prop == "italic":
        _set_attr(r_pr, "i", None if value is None else ("1" if value else "0"))
    elif run_prop == "font_latin":
        latin = r_pr.find("./a:latin", NS)
        if latin is None:
            latin = r_pr.makeelement(f"{{{A_NS}}}latin", {})
            r_pr.append(latin)
        _set_attr(latin, "typeface", value)
    else:
        raise ValueError(f"unsupported run property: {run_prop}")


def _apply_table(element: ET.Element, prop_path: str, value: Any) -> None:
    tbl = element.find("./a:graphic/a:graphicData/a:tbl", NS)
    if tbl is None:
        raise ValueError("no table to repair")
    col_match = re.match(r"column_widths_emu\[(\d+)\]", prop_path)
    if col_match:
        cols = tbl.findall("./a:tblGrid/a:gridCol", NS)
        idx = int(col_match.group(1))
        if idx >= len(cols):
            raise IndexError("column index out of range")
        _set_attr(cols[idx], "w", None if value is None else int(round(float(value))))
        return
    row_match = re.match(r"rows\[(\d+)\]\.height_emu", prop_path)
    if row_match:
        rows = tbl.findall("./a:tr", NS)
        idx = int(row_match.group(1))
        if idx >= len(rows):
            raise IndexError("row index out of range")
        _set_attr(rows[idx], "h", None if value is None else int(round(float(value))))
        return
    raise ValueError(f"unsupported table property: {prop_path}")


_HANDLERS = {
    "geometry": _apply_geometry,
    "fill": _apply_fill,
    "line": _apply_line,
    "media": _apply_crop,
    "typography": _apply_typography,
    "table": _apply_table,
}


_TOKEN_ALIASES = {"geometry_emu": "geometry", "connector": "line"}


def _apply_property(element: ET.Element, prop_path: str, value: Any) -> None:
    root_token = prop_path.split(".", 1)[0].split("[")[0]
    root_token = _TOKEN_ALIASES.get(root_token, root_token)
    handler = _HANDLERS.get(root_token)
    if handler is None:
        raise ValueError(f"unsupported property path: {prop_path}")
    sub_path = prop_path.split(".", 1)[1] if "." in prop_path else ""
    handler(element, sub_path, value)


# --------------------------------------------------------------------------- #
# layer-order rebuild (per container)
# --------------------------------------------------------------------------- #
def _rebuild_container_order(root: ET.Element, targets: dict[str, int]) -> None:
    """Place mapped shapes at their reference spTree slots; others fill the rest."""
    sp_tree = _sp_tree(root)
    children = list(sp_tree)
    prefix = [child for child in children if _local(child.tag) not in _SHAPE_KINDS]
    shapes = [child for child in children if _local(child.tag) in _SHAPE_KINDS]
    if not shapes:
        return
    offset = len(prefix)

    slots: dict[int, ET.Element] = {}
    overflow: list[ET.Element] = []
    for position, shape in enumerate(shapes):
        shape_id = _shape_id(shape)
        target = targets.get(str(shape_id))
        if target is None:
            overflow.append(shape)
            continue
        slot = int(target) - offset
        if slot < 0 or slot >= len(shapes):
            overflow.append(shape)
            continue
        slots.setdefault(slot, shape)

    ordered: list[ET.Element] = []
    for slot in range(len(shapes)):
        if slot in slots:
            ordered.append(slots[slot])
    ordered.extend(shape for shape in overflow if shape not in ordered)

    for shape in shapes:
        sp_tree.remove(shape)
    for shape in ordered:
        sp_tree.append(shape)


# --------------------------------------------------------------------------- #
# execution
# --------------------------------------------------------------------------- #
def _directive_iterable(plan: Any) -> list[dict[str, Any]]:
    if isinstance(plan, dict):
        return list(plan.get("directives", []))
    if isinstance(plan, FidelityReport) or hasattr(plan, "issues"):
        from .fidelity_repair import repair_plan_dict

        return list(repair_plan_dict(plan)["directives"])
    return list(plan or [])


def execute_repair_plan(
    pptx_path: str | Path,
    plan: Any,
    output_path: str | Path,
    *,
    slide_index: int = 1,
) -> dict[str, Any]:
    """Apply every executable directive; never mutate the source package."""
    source = Path(pptx_path)
    output = Path(output_path)
    directives = _directive_iterable(plan)

    entries: dict[str, bytes] = {}
    with zipfile.ZipFile(source) as zf:
        for name in zf.namelist():
            entries[name] = zf.read(name)
        parts = _locate_parts(zf, slide_index=slide_index)

    roots: dict[str, ET.Element | None] = {}
    for label, part in parts.items():
        roots[label] = ET.fromstring(entries[part]) if part and part in entries else None

    report: dict[str, Any] = {"applied": [], "skipped": [], "failed": [], "reorder_targets": {}}
    reorder_targets: dict[str, dict[str, int]] = report["reorder_targets"]

    for directive in directives:
        path = str(directive.get("path", ""))
        operation = str(directive.get("operation", "restore_property"))
        reference_value = directive.get("reference")
        entry: dict[str, Any] = {"path": path, "operation": operation}

        if ".added[" in path or ".removed[" in path:
            entry["status"] = "skipped"
            entry["reason"] = "layer addition/removal requires structural rebuild"
            report["skipped"].append(entry)
            continue

        match = _PATH_RE.match(path) or _ZPATH_RE.match(path)
        try:
            if not match:
                raise ValueError("path outside slide/master/layout shape scope")
            groups = match.groups()
            container = groups[0]
            shape_token = groups[1]
            child_index = groups[2] if len(groups) > 2 and groups[2] else None
            prop_path = groups[-1] or ""
            root = roots.get(container)
            if root is None:
                raise ValueError(f"container {container} unavailable")

            if operation == "restore_layer_order" or prop_path in ("z_index", "stack.global_z", "global_render_order"):
                if reference_value is None:
                    raise ValueError("layer order repair needs a reference position")
                reorder_targets.setdefault(container, {})[shape_token] = int(reference_value)
                entry["status"] = "applied"
                entry["detail"] = f"target spTree slot {reference_value}"
                report["applied"].append(entry)
                continue

            if "rendered_bbox" in prop_path or prop_path in ("stack.below", "stack.above", "stack"):
                entry["status"] = "skipped"
                entry["reason"] = "derived value; repaired through x/y/cx/cy/z_index"
                report["skipped"].append(entry)
                continue

            if operation in ("restore_page_kind", "restore_media_asset"):
                entry["status"] = "skipped"
                entry["reason"] = "not expressible as a minimal property edit; needs rebuild"
                report["skipped"].append(entry)
                continue
            if path.endswith("semantic_xml"):
                entry["status"] = "skipped"
                entry["reason"] = "evidence-level difference; structured properties already compared"
                report["skipped"].append(entry)
                continue

            element = _find_by_id(root, shape_token)
            if child_index is not None:
                group_children = [child for child in element if _local(child.tag) in _SHAPE_KINDS]
                element = group_children[int(child_index)]
            _apply_property(element, prop_path, reference_value)
            entry["status"] = "applied"
            report["applied"].append(entry)
        except Exception as exc:  # noqa: BLE001 - record per-directive failure
            entry["status"] = "failed"
            entry["reason"] = f"{type(exc).__name__}: {exc}"
            report["failed"].append(entry)

    # apply layer reordering after per-property edits, per container
    for label, targets in reorder_targets.items():
        root = roots.get(label)
        if root is not None:
            _rebuild_container_order(root, targets)

    for label, root in roots.items():
        part = parts[label]
        if root is not None and part:
            entries[part] = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    _write_zip(source, entries, output)
    report["output"] = str(output)
    report["schema"] = "template-dna/fidelity-repair-executor/v1"
    return report


def verify_repair(
    reference: str | Path,
    candidate: str | Path,
    *,
    slide_index: int = 1,
    tolerance: float = 0.0005,
) -> FidelityReport:
    """Re-extract both packages and re-run the structural comparison."""
    return compare_dna(
        extract_fidelity_dna(reference, slide_index=slide_index),
        extract_fidelity_dna(candidate, slide_index=slide_index),
        tolerance=tolerance,
    )


__all__ = ["execute_repair_plan", "verify_repair"]
