from ppt_agent.relationships import build_relationship_graph


def test_relationship_graph_recurses_to_arbitrary_group_depth_and_deduplicates_edges():
    dna = {
        "slides": [{
            "slide": 1,
            "shapes": [{
                "id": "10", "z_index": 0,
                "children": [{
                    "id": "11", "z_index": 1,
                    "children": [{"id": "12", "z_index": 2}],
                }],
            }, {"id": "20", "z_index": 3}],
        }]
    }
    graph = build_relationship_graph(dna)
    edges = {(e["source"], e["target"], e["relation"]) for e in graph["edges"]}
    assert ("1", "10", "contains") in edges
    assert ("10", "11", "contains") in edges
    assert ("11", "12", "contains") in edges
    assert ("1", "20", "contains") in edges
    assert ("10", "20", "below") in edges
    assert len(graph["nodes"]) == len({node["id"] for node in graph["nodes"]})
    assert len(graph["edges"]) == len(edges)
