from __future__ import annotations

from copy import deepcopy
from typing import Any


def normalize_dna(dna: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(dna)
    slides = out.setdefault("slides", [])
    masters = out.setdefault("masters", [])
    index: dict[str, Any] = {"slides": {}, "masters": {}, "layouts": {}, "elements": {}}
    for master in masters:
        name = str(master.get("name") or master.get("id") or f"master-{len(index['masters']) + 1}")
        index["masters"][name] = {"id": master.get("id"), "name": name, "layout_count": len(master.get("layouts") or [])}
        for layout in master.get("layouts") or []:
            lid = str(layout.get("id") or layout.get("name") or f"layout-{len(index['layouts']) + 1}")
            index["layouts"][lid] = {"master": name, "name": layout.get("name"), "id": layout.get("id")}
    for number, slide in enumerate(slides, 1):
        sid = str(slide.get("slide") or number)
        index["slides"][sid] = {
            "number": number,
            "role": slide.get("role", "body"),
            "layout": slide.get("layout_name"),
            "layout_signature": slide.get("layout_signature"),
            "inheritance": slide.get("inheritance"),
        }
        for shape in slide.get("shapes") or []:
            eid = str(shape.get("id") or f"slide-{sid}-shape-{len(index['elements']) + 1}")
            index["elements"][eid] = {
                "slide": sid,
                "parent_id": shape.get("parent_id"),
                "z_index": shape.get("z_index", shape.get("z_order")),
                "type": shape.get("type"),
            }
    out["structural_index"] = index
    out["dna_capabilities"] = {
        "element_properties": True,
        "z_order": True,
        "parent_child": True,
        "master_layout": bool(masters),
        "slide_roles": True,
        "raw_ooxml": True,
        "alpha_transparency": True,
        "page_background": True,
        "theme": "theme" in out,
    }
    return out
