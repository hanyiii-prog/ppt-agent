from ppt_agent.template import _shape_record


class FakeShape:
    shape_id = 7
    name = "SemiTransparent Box"
    shape_type = 1
    left = 914400
    top = 457200
    width = 1828800
    height = 914400
    rotation = 12
    flip_horizontal = False
    flip_vertical = True

    class _Element:
        xml = '<p:sp><a:solidFill><a:srgbClr val="FF0000"><a:alpha val="50000"/></a:srgbClr></a:solidFill></p:sp>'

    _element = _Element()

    class _Fill:
        transparency = 0.5
        type = None

        class _Color:
            rgb = "FF0000"

        fore_color = _Color()

    fill = _Fill()
    line = None


def test_shape_record_preserves_geometry_style_and_fidelity():
    record = _shape_record(FakeShape(), z_index=3, parent_id="group-1")

    assert record["id"] == "7"
    assert record["z_index"] == 3
    assert record["z_order"] == 3
    assert record["parent_id"] == "group-1"
    assert record["geometry"]["left"] == 1.0
    assert record["geometry"]["top"] == 0.5
    assert record["geometry"]["rotation"] == 12
    assert record["geometry"]["flip_vertical"] is True
    assert record["style"]["fill"]["rgb"] == "FF0000"
    assert record["style"]["fill"]["alpha"] == 50000
    assert record["style"]["fill"]["opacity"] == 0.5
    assert record["style"]["fill"]["transparency"] == 0.5
    assert record["fidelity"]["raw_xml"]
    assert record["fidelity"]["alpha_transforms"] is True
