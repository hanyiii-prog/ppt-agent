from ppt_agent.dna_normalize import normalize_dna


def test_normalize_dna_builds_relationship_indexes():
    result = normalize_dna({
        "slides": [{"slide": 1, "role": "first", "layout_name": "Title", "shapes": [{"id": "s1", "parent_id": "g1", "z_index": 4, "type": "TEXT"}]}],
        "masters": [{"name": "Master", "layouts": [{"id": "l1", "name": "Title"}]}],
        "theme": {},
    })
    assert result["structural_index"]["slides"]["1"]["role"] == "first"
    assert result["structural_index"]["layouts"]["l1"]["master"] == "Master"
    assert result["structural_index"]["elements"]["s1"]["parent_id"] == "g1"
    assert result["dna_capabilities"]["z_order"] is True
