from ppt_agent.relationships import build_relationship_graph


def test_relationship_graph_links_master_layout_slide_and_group_child():
    dna = {
        "masters": [{"name": "Master A", "layouts": [{"name": "Title"}]}],
        "slides": [{
            "slide": 1,
            "role": "first",
            "layout_name": "Title",
            "shapes": [{"id": "10", "z_index": 0, "children": [{"id": "11", "z_index": 0}]}],
        }],
    }
    graph = build_relationship_graph(dna)
    edges = {(e["source"], e["target"], e["relation"]) for e in graph["edges"]}
    assert ("Master A", "Title", "inherits") in edges
    assert ("Title", "1", "inherits") in edges
    assert ("1", "10", "contains") in edges
    assert ("10", "11", "contains") in edges
