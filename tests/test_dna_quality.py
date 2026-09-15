from ppt_agent.dna_quality import inspect_dna


def test_quality_report_covers_fidelity_and_page_roles():
    report = inspect_dna({
        "schema": "template-dna/v0.3",
        "presentation": {}, "theme": {}, "masters": [],
        "slides": [
            {"slide": 1, "role": "first", "shapes": [{"id": "a", "type": "TEXT", "geometry": {}, "style": {}, "fidelity": {"raw_xml": "x", "alpha_transforms": True}}]},
            {"slide": 2, "role": "last", "shapes": []},
        ],
    })
    assert report["ok"] is True
    assert report["raw_xml_count"] == 1
    assert report["alpha_transform_count"] == 1
    assert report["first_slide_is_first"] is True
    assert report["last_slide_is_last"] is True
