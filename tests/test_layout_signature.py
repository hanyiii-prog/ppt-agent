from ppt_agent.layout_signature import canonical_layout_signature


def test_layout_signature_is_order_and_value_stable():
    shapes = [
        {"id": "a", "type": "TEXT", "z_index": 1, "geometry": {"left": 1, "top": 2, "width": 3, "height": 4}},
        {"id": "b", "type": "RECT", "z_index": 0, "geometry": {"left": 5, "top": 6, "width": 7, "height": 8}},
    ]
    reordered = list(reversed(shapes))
    assert canonical_layout_signature(shapes) == canonical_layout_signature(reordered)

    changed = [{**shapes[0], "geometry": {**shapes[0]["geometry"], "width": 3.1}}, shapes[1]]
    assert canonical_layout_signature(shapes) != canonical_layout_signature(changed)
