from ppt_agent.visual_grammar import extract_visual_grammar


def test_visual_grammar_preserves_special_surfaces_and_reuse_signal():
    dna = {
        "slides": [
            {"slide": 1, "role": "first", "layout_signature": "cover", "shapes": [{"id": "1", "type": "TEXT"}]},
            {"slide": 2, "role": "body", "layout_signature": "body", "shapes": [{"id": "2", "type": "TEXT"}]},
            {"slide": 3, "role": "last", "layout_signature": "closing", "shapes": [{"id": "3", "type": "TEXT"}]},
        ]
    }
    grammar = extract_visual_grammar(dna)
    assert grammar["roles"] == {"first": 1, "body": 1, "last": 1}
    assert grammar["element_type_frequency"]["TEXT"] == 3
    assert grammar["rules"]["first_slide_is_special_surface"] is True
    assert grammar["rules"]["last_slide_is_special_surface"] is True
    assert grammar["rules"]["body_layout_reuse_detected"] is False


def test_visual_grammar_derives_canonical_signature_when_missing():
    dna = {
        "slides": [
            {"slide": 1, "role": "body", "shapes": [{"id": "a", "type": "TEXT", "geometry": {"left": 0, "top": 0, "width": 10, "height": 20}}]},
            {"slide": 2, "role": "body", "shapes": [{"id": "b", "type": "TEXT", "geometry": {"left": 0, "top": 0, "width": 10, "height": 20}}]},
        ]
    }
    grammar = extract_visual_grammar(dna)
    assert len(grammar["layout_signature_frequency"]) == 1
    assert grammar["reusable_layouts"]
    assert grammar["rules"]["body_layout_reuse_detected"] is True
