from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: str
    z_index: int | None = None
    parent_id: str | None = None
    source: str = "slide"
    order: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    relation: str
    order: int | None = None


@dataclass
class SceneGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    roots: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.__dict__ for n in self.nodes],
            "edges": [e.__dict__ for e in self.edges],
            "roots": list(self.roots),
        }


def _shape_nodes(shapes: Iterable[dict[str, Any]], *, source: str = "slide") -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    def visit(items: Iterable[dict[str, Any]], parent_id: str | None = None) -> None:
        for order, shape in enumerate(items):
            shape_id = str(shape.get("id") or f"shape-{len(nodes) + 1}")
            node = GraphNode(
                id=shape_id,
                kind=str(shape.get("type") or "unknown"),
                z_index=shape.get("z_index", shape.get("z_order")),
                parent_id=shape.get("parent_id") or parent_id,
                source=source,
                order=order,
                metadata={
                    "name": shape.get("name"),
                    "is_group": bool(shape.get("is_group")),
                    "placeholder": shape.get("placeholder"),
                },
            )
            nodes.append(node)
            if node.parent_id:
                edges.append(GraphEdge(node.parent_id, node.id, "contains", order))
            for child in shape.get("children") or []:
                visit([child], shape_id)

    visit(shapes)
    return nodes, edges


def build_scene_graph(shapes: Iterable[dict[str, Any]], *, source: str = "slide") -> SceneGraph:
    nodes, edges = _shape_nodes(shapes, source=source)
    ids = {node.id for node in nodes}
    for node in nodes:
        if node.parent_id is None or node.parent_id not in ids:
            if node.id not in {root for root in [edge.target for edge in edges if edge.relation == "contains"]}:
                pass
    roots = [node.id for node in nodes if node.parent_id is None or node.parent_id not in ids]

    # Preserve the exact stacking sequence as explicit edges. Do not infer
    # visual overlap: z-order is the authoritative PPT drawing order.
    ordered = sorted((n for n in nodes if n.z_index is not None), key=lambda n: (n.z_index, n.order))
    for lower, upper in zip(ordered, ordered[1:]):
        edges.append(GraphEdge(lower.id, upper.id, "below", upper.z_index))
    return SceneGraph(nodes=nodes, edges=edges, roots=roots)


def validate_scene_graph(graph: SceneGraph) -> list[str]:
    errors: list[str] = []
    ids = [n.id for n in graph.nodes]
    if len(ids) != len(set(ids)):
        errors.append("duplicate node id")
    known = set(ids)
    for edge in graph.edges:
        if edge.source not in known:
            errors.append(f"edge source missing: {edge.source}")
        if edge.target not in known:
            errors.append(f"edge target missing: {edge.target}")
    for node in graph.nodes:
        if node.parent_id and node.parent_id not in known:
            errors.append(f"parent missing: {node.id}->{node.parent_id}")
    return errors
