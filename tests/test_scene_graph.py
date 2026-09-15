from ppt_agent.scene_graph import build_scene_graph, validate_scene_graph


def test_scene_graph_preserves_parent_and_z_order():
    graph = build_scene_graph([
        {"id": "back", "type": "SHAPE", "z_index": 0, "geometry": {}, "style": {}},
        {"id": "group", "type": "GROUP", "z_index": 1, "is_group": True, "children": [
            {"id": "text", "type": "TEXT_BOX", "z_index": 2, "geometry": {}, "style": {}}
        ]},
        {"id": "front", "type": "PICTURE", "z_index": 3, "geometry": {}, "style": {}},
    ])
    assert graph.roots == ["back", "group", "front"]
    assert any(e.relation == "contains" and e.source == "group" and e.target == "text" for e in graph.edges)
    assert any(e.relation == "below" and e.source == "back" and e.target == "group" for e in graph.edges)
    assert validate_scene_graph(graph) == []
