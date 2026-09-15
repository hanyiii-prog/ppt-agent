from ppt_agent.visual_grammar import extract_visual_grammar


def test_visual_grammar_preserves_special_surfaces_and_reuse_signal():
    dna = {
        "slides": [
            {"slide": 1, "role": "first", "layout_signature": {"kind": "cover"}, "shapes": [{"id": "1", "type": "TEXT"}]},
            {"slide": 2, "role": "body", "layout_signature": {"kind": "body"}, "shapes": [{"id": "2", "type": "TEXT"}]},
            {"slide": 3, "role": "last", "layout_signature": {"kind": "closing"}, "shapes": [{"id": "3", "type": "TEXT"}]},
        ]
    }
    grammar = extract_visual_grammar(dna)
    assert grammar["roles"] == {"first": 1, "body": 1, "last": 1}
    assert grammar["element_type_frequency"]["TEXT"] == 3
    assert grammar["rules"]["first_slide_is_special_surface"] is True
    assert grammar["rules"]["last_slide_is_special_surface"] is True
