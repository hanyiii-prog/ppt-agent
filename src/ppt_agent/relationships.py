from __future__ import annotations

from typing import Any


def _shape_ids(shapes: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for shape in shapes:
        sid = shape.get("id")
        if sid is not None:
            ids.append(str(sid))
        ids.extend(_shape_ids(shape.get("children") or []))
    return ids


def build_relationship_graph(dna: dict[str, Any]) -> dict[str, Any]:
    """Build explicit presentation inheritance and containment relationships."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    masters = dna.get("masters") or []
    for mi, master in enumerate(masters):
        master_id = str(master.get("id") or master.get("name") or f"master-{mi + 1}")
        nodes.append({"id": master_id, "kind": "master", "name": master.get("name")})
        for li, layout in enumerate(master.get("layouts") or []):
            layout_id = str(layout.get("id") or layout.get("name") or f"{master_id}-layout-{li + 1}")
            nodes.append({"id": layout_id, "kind": "layout", "name": layout.get("name"), "master_id": master_id})
            edges.append({"source": master_id, "target": layout_id, "relation": "inherits"})

    for number, slide in enumerate(dna.get("slides") or [], 1):
        slide_id = str(slide.get("slide") or number)
        nodes.append({"id": slide_id, "kind": "slide", "role": slide.get("role"), "layout_name": slide.get("layout_name")})
        layout_name = slide.get("layout_name")
        if layout_name:
            for master in masters:
                for layout in master.get("layouts") or []:
                    if layout.get("name") == layout_name:
                        layout_id = str(layout.get("id") or layout.get("name"))
                        edges.append({"source": layout_id, "target": slide_id, "relation": "inherits"})
        for shape in slide.get("shapes") or []:
            sid = str(shape.get("id"))
            nodes.append({"id": sid, "kind": "element", "slide_id": slide_id, "parent_id": shape.get("parent_id"), "z_index": shape.get("z_index", shape.get("z_order"))})
            parent = shape.get("parent_id")
            if parent:
                edges.append({"source": str(parent), "target": sid, "relation": "contains"})
            else:
                edges.append({"source": slide_id, "target": sid, "relation": "contains"})
            for child in shape.get("children") or []:
                cid = str(child.get("id"))
                nodes.append({"id": cid, "kind": "element", "slide_id": slide_id, "parent_id": sid, "z_index": child.get("z_index", child.get("z_order"))})
                edges.append({"source": sid, "target": cid, "relation": "contains"})

    return {"nodes": nodes, "edges": edges}
