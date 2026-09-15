from ppt_agent.relationships import build_relationship_graph


def test_relationship_graph_links_master_layout_slide_and_group_child():
    dna = {
        "masters": [{"name": "Master A", "layouts": [{"name": "Title", "id": "layout-title"}]}],
        "slides": [{
            "slide": 1,
            "role": "first",
            "layout_name": "Title",
            "shapes": [{"id": "10", "z_index": 0, "children": [{"id": "11", "z_index": 0}]}],
        }],
    }
    graph = build_relationship_graph(dna)
    edges = {(e["source"], e["target"], e["relation"]) for e in graph["edges"]}
    assert ("Master A", "layout-title", "inherits") in edges
    assert ("layout-title", "1", "inherits") in edges
    assert ("1", "10", "contains") in edges
    assert ("10", "11", "contains") in edges


def test_relationship_graph_recurses_and_orders_sibling_roots():
    dna = {
        "slides": [{
            "slide": 2,
            "shapes": [
                {"id": "a", "z_index": 10, "children": [{"id": "a1", "children": [{"id": "a2"}]}]},
                {"id": "b", "z_index": 20},
                {"id": "a-duplicate", "parent_id": "a", "z_index": 30},
            ],
        }],
    }
    graph = build_relationship_graph(dna)
    edges = {(e["source"], e["target"], e["relation"]) for e in graph["edges"]}
    assert ("a", "a1", "contains") in edges
    assert ("a1", "a2", "contains") in edges
    assert ("a", "a-duplicate", "contains") in edges
    assert ("a", "b", "below") in edges


def test_relationship_graph_deduplicates_nodes_and_edges():
    dna = {
        "slides": [{
            "slide": 3,
            "shapes": [
                {"id": "x", "z_index": 0},
                {"id": "x", "z_index": 0},
            ],
        }],
    }
    graph = build_relationship_graph(dna)
    x_nodes = [node for node in graph["nodes"] if node["id"] == "x"]
    x_edges = [edge for edge in graph["edges"] if edge["target"] == "x"]
    assert len(x_nodes) == 1
    assert len(x_edges) == 1
