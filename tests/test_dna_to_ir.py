from ppt_agent.dna_to_ir import template_dna_to_ir


def test_template_dna_to_ir_preserves_slide_roles_and_fidelity():
    dna = {
        "schema": "template-dna/v0.3",
        "source": "fixture.pptx",
        "presentation": {"slide_size_inches": {"width": 13.333, "height": 7.5}},
        "theme": {"colors": {"dk1": "000000"}},
        "masters": [{"name": "Master 1", "shapes": []}],
        "global_style_statistics": {"fonts": [["Aptos", 3]]},
        "slides": [
            {
                "slide": 1,
                "role": "first",
                "layout_name": "Title Slide",
                "shapes": [
                    {
                        "id": "10",
                        "name": "Title",
                        "type": "TEXT_BOX",
                        "z_index": 4,
                        "parent_id": "group-1",
                        "geometry": {"left": 1, "top": 2, "width": 5, "height": 1},
                        "style": {"fill": {"rgb": "FFFFFF", "alpha": 0.4}},
                        "fidelity": {"raw_xml": "..."},
                        "text": {"plain_text": "Hello"},
                    }
                ],
            },
            {"slide": 2, "role": "last", "layout_name": "Blank", "shapes": []},
        ],
        "special_surfaces": {"first": {}, "last": {}},
    }

    presentation = template_dna_to_ir(dna)

    assert presentation.slides[0].purpose == "cover"
    assert presentation.slides[1].purpose == "closing"
    component = presentation.slides[0].components[0]
    assert component.type == "text"
    assert component.text == "Hello"
    assert component.x == 1
    assert component.style["fill"]["alpha"] == 0.4
    assert component.data["fidelity"]["z_index"] == 4
    assert component.data["fidelity"]["parent_id"] == "group-1"
    assert presentation.theme["masters"][0]["name"] == "Master 1"
