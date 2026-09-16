from __future__ import annotations

import hashlib
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"p": P_NS, "a": A_NS, "r": R_NS}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _rel_map(xml_bytes: bytes) -> dict[str, str]:
    root = ET.fromstring(xml_bytes)
    return {node.get("Id"): node.get("Target") for node in root if node.get("Id")}


def _zip_path(base_dir: str, target: str) -> str:
    return posixpath.normpath(posixpath.join(base_dir, target)).lstrip("/")


def _shape_record(element: ET.Element, z_index: int, rels: dict[str, str], parent_id: str | None = None) -> dict[str, Any] | None:
    kind = _local(element.tag)
    if kind not in {"sp", "pic", "graphicFrame", "cxnSp", "grpSp"}:
        return None

    c_nv = element.find("./p:nvSpPr/p:cNvPr", NS)
    shape_id = c_nv.get("id") if c_nv is not None else None
    name = c_nv.get("name") if c_nv is not None else None
    xfrm = element.find(".//a:xfrm", NS)
    geometry = None
    if xfrm is not None:
        off = xfrm.find("./a:off", NS)
        ext = xfrm.find("./a:ext", NS)
        if off is not None and ext is not None:
            geometry = {
                "x": int(off.get("x", 0)),
                "y": int(off.get("y", 0)),
                "w": int(ext.get("cx", 0)),
                "h": int(ext.get("cy", 0)),
            }

    embedded = element.find(".//*[@r:embed]", NS)
    relationship_id = embedded.get(f"{{{R_NS}}}embed") if embedded is not None else None
    source_rect = element.find(".//a:srcRect", NS)

    record: dict[str, Any] = {
        "z_index": z_index,
        "parent_id": parent_id,
        "shape_id": shape_id,
        "name": name,
        "kind": kind,
        "geometry_emu": geometry,
        "relationship_id": relationship_id,
        "target": rels.get(relationship_id) if relationship_id else None,
        "source_rect": dict(source_rect.attrib) if source_rect is not None else None,
        # Fidelity escape hatch: keep the original OOXML for anything a high-level
        # library cannot faithfully model (custom geometry, gradients, alpha,
        # effects, inheritance, connector settings, etc.).
        "raw_xml": ET.tostring(element, encoding="unicode"),
    }

    sp_pr = element.find("./p:spPr", NS)
    if sp_pr is not None:
        record["spPr_xml"] = ET.tostring(sp_pr, encoding="unicode")
        cust_geom = sp_pr.find("./a:custGeom", NS)
        if cust_geom is not None:
            record["custom_geometry_xml"] = ET.tostring(cust_geom, encoding="unicode")

    tx_body = element.find("./p:txBody", NS)
    if tx_body is not None:
        record["text_body_xml"] = ET.tostring(tx_body, encoding="unicode")

    placeholder = element.find("./p:nvSpPr/p:nvPr/p:ph", NS)
    if placeholder is not None:
        record["placeholder"] = dict(placeholder.attrib)

    if kind == "grpSp":
        children = []
        for child_index, child in enumerate(list(element)):
            child_record = _shape_record(child, child_index, rels, shape_id)
            if child_record is not None:
                children.append(child_record)
        record["children"] = children

    return record


def _shape_records(root: ET.Element, rels: dict[str, str]) -> list[dict[str, Any]]:
    sp_tree = root.find(".//p:spTree", NS)
    if sp_tree is None:
        return []
    records = []
    for index, element in enumerate(list(sp_tree)):
        record = _shape_record(element, index, rels)
        if record is not None:
            records.append(record)
    return records


def _raw_xml(zf: zipfile.ZipFile, path: str) -> str | None:
    try:
        return zf.read(path).decode("utf-8")
    except (KeyError, UnicodeDecodeError):
        return None


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


def extract_fidelity_dna(path: str | Path, slide_index: int = 1) -> dict[str, Any]:
    """Extract a loss-minimizing OOXML fidelity layer for one slide.

    This complements the semantic Template DNA extractor. The semantic layer is
    intended for reasoning; this layer preserves exact package-level information
    required for high-fidelity reconstruction: master/layout XML, stacking order,
    custom geometry, gradient/alpha/effect XML, image relationships and crop
    rectangles, theme XML, and the raw slide/layout XML.
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

        slide_count = len(slide_paths)
        return {
            "schema": "template-dna/fidelity/v1",
            "source": str(source),
            "slide_index": slide_index,
            "surface_role": _slide_role(slide_index, slide_count),
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
            },
            "master": {
                "path": master_path,
                "raw_xml": _raw_xml(zf, master_path) if master_path else None,
                "relationships_xml": master_rels_xml.decode("utf-8") if master_rels_xml else None,
                "shapes": _shape_records(master_root, master_rels) if master_root is not None else [],
            },
            "layout": {
                "path": layout_path,
                "raw_xml": _raw_xml(zf, layout_path),
                "relationships_xml": layout_rels_xml.decode("utf-8"),
                "shapes": _shape_records(layout_root, layout_rels),
            },
            "slide": {
                "path": slide_path,
                "raw_xml": _raw_xml(zf, slide_path),
                "relationships_xml": slide_rels_xml.decode("utf-8"),
                "shapes": _shape_records(slide_root, slide_rels),
            },
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
        __import__("json").dumps(dna, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with zipfile.ZipFile(source) as zf:
        assets_dir = destination / "assets"
        assets_dir.mkdir(exist_ok=True)
        for package_path in dna["assets"]:
            target = assets_dir / Path(package_path).name
            target.write_bytes(zf.read(package_path))
    return destination / "dna.json"
