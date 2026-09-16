from __future__ import annotations

from typing import Any, Iterator


def _walk_shapes(shapes: list[dict[str, Any]], inherited_parent: str | None = None) -> Iterator[tuple[dict[str, Any], str, str | None]]:
    """Yield every nested element once with its effective parent."""
    for shape in shapes:
        sid = shape.get("id")
        if sid is None:
            continue
        sid = str(sid)
        parent = str(shape["parent_id"]) if shape.get("parent_id") is not None else inherited_parent
        yield shape, sid, parent
        yield from _walk_shapes(shape.get("children") or [], sid)


def build_relationship_graph(dna: dict[str, Any]) -> dict[str, Any]:
    """Build explicit master→layout→slide inheritance and recursive containment."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    edge_keys: set[tuple[str, str, str]] = set()

    def add_node(node: dict[str, Any]) -> None:
        if node["id"] not in node_ids:
            node_ids.add(node["id"])
            nodes.append(node)

    def add_edge(source: str, target: str, relation: str) -> None:
        key = (source, target, relation)
        if key not in edge_keys:
            edge_keys.add(key)
            edges.append({"source": source, "target": target, "relation": relation})

    masters = dna.get("masters") or []
    layout_ids_by_name: dict[str, list[str]] = {}
    for mi, master in enumerate(masters):
        master_id = str(master.get("id") or master.get("name") or f"master-{mi + 1}")
        add_node({"id": master_id, "kind": "master", "name": master.get("name")})
        for li, layout in enumerate(master.get("layouts") or []):
            layout_id = str(layout.get("id") or layout.get("name") or f"{master_id}-layout-{li + 1}")
            add_node({"id": layout_id, "kind": "layout", "name": layout.get("name"), "master_id": master_id})
            add_edge(master_id, layout_id, "inherits")
            if layout.get("name"):
                layout_ids_by_name.setdefault(str(layout["name"]), []).append(layout_id)

    for number, slide in enumerate(dna.get("slides") or [], 1):
        slide_id = str(slide.get("slide") or number)
        add_node({"id": slide_id, "kind": "slide", "role": slide.get("role"), "layout_name": slide.get("layout_name")})
        for layout_id in layout_ids_by_name.get(str(slide.get("layout_name")), []):
            add_edge(layout_id, slide_id, "inherits")

        roots: list[tuple[str, int]] = []
        seen_root_ids: set[str] = set()
        for shape, sid, parent in _walk_shapes(slide.get("shapes") or []):
            add_node({
                "id": sid,
                "kind": "element",
                "slide_id": slide_id,
                "parent_id": parent,
                "z_index": shape.get("z_index", shape.get("z_order")),
            })
            add_edge(parent or slide_id, sid, "contains")
            z = shape.get("z_index", shape.get("z_order"))
            if parent is None and isinstance(z, (int, float)) and sid not in seen_root_ids:
                seen_root_ids.add(sid)
                roots.append((sid, int(z)))

        roots.sort(key=lambda item: (item[1], item[0]))
        for (lower, _), (upper, _) in zip(roots, roots[1:]):
            add_edge(lower, upper, "below")

    return {"nodes": nodes, "edges": edges}
