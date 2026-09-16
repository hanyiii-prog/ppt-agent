from ppt_agent.template import _fill_info


class FakeShape:
    class _Element:
        xml = '<p:sp><a:solidFill><a:srgbClr val="FF0000"><a:alphaModFix val="25000"/></a:srgbClr></a:solidFill></p:sp>'

    _element = _Element()

    class _Fill:
        type = None

        class _Color:
            rgb = "FF0000"

        fore_color = _Color()

        @property
        def transparency(self):
            raise AttributeError("not exposed")

    fill = _Fill()


def test_fill_alpha_transform_is_preserved_when_python_pptx_does_not_expose_it():
    info = _fill_info(FakeShape())
    assert info["alpha"] == 25000
    assert info["opacity"] == 0.25
    assert info["transparency"] == 0.75


def test_fill_alpha_and_transparency_are_consistent():
    class Shape(FakeShape):
        class _Fill(FakeShape._Fill):
            transparency = 0.2

        fill = _Fill()

    info = _fill_info(Shape())
    assert info["alpha"] == 80000
    assert info["opacity"] == 0.8
    assert info["transparency"] == 0.2
