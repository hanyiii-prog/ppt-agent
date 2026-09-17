"""Structural Diff 2.0 tests: taxonomy codes, semantic XML, media by content."""
from ppt_agent.fidelity_diff import compare_dna, semantic_canonical_xml, semantic_xml_hash
from ppt_agent.fidelity_repair import plan_from_report

from fidelity_fixtures import build_rich_pptx, mutate_pptx
from ppt_agent.fidelity import extract_fidelity_dna


# --------------------------------------------------------------------------- #
# semantic XML canonicalization
# --------------------------------------------------------------------------- #
def test_semantic_hash_ignores_namespace_prefix_and_attribute_order():
    ns = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    a = f'<a:srgbClr {ns}val="1185FE"><a:alpha val="65000"/></a:srgbClr>'
    b = '<ns0:srgbClr xmlns:ns0="http://schemas.openxmlformats.org/drawingml/2006/main" val="1185FE"><ns0:alpha val="65000"/></ns0:srgbClr>'
    assert semantic_xml_hash(a) == semantic_xml_hash(b)


def test_semantic_hash_detects_real_changes():
    ns = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    a = f'<a:srgbClr {ns}val="1185FE"/>'
    b = f'<a:srgbClr {ns}val="09437F"/>'
    assert semantic_xml_hash(a) != semantic_xml_hash(b)
    assert semantic_canonical_xml("not-xml-at-all") is None


# --------------------------------------------------------------------------- #
# diff taxonomy
# --------------------------------------------------------------------------- #
def test_layer_swap_reports_reordered_not_cascading_property_diffs():
    def deck(z_a, z_b):
        return {"schema": "s", "slide": {"shapes": [
            {"shape_id": "a", "name": "A", "z_index": z_a, "geometry_emu": {"x": 0, "y": 0, "cx": 10, "cy": 10}},
            {"shape_id": "b", "name": "B", "z_index": z_b, "geometry_emu": {"x": 10, "y": 0, "cx": 10, "cy": 10}},
        ]}}

    report = compare_dna(deck(0, 1), deck(1, 0))
    assert not report.passed
    assert report.codes.get("layer.reordered", 0) >= 1
    # B matched B and A matched A: no geometry/style false positives
    assert not report.codes.get("geometry.position")
    assert not report.codes.get("style.fill")


def test_media_diff_compares_hash_not_relationship_id():
    ref = {"schema": "s", "slide": {"shapes": [
        {"shape_id": "1", "media": {"relationship_id": "rId2", "target": "ppt/media/image1.png", "sha256": "aa", "crop": None}},
    ]}}
    cand = {"schema": "s", "slide": {"shapes": [
        {"shape_id": "1", "media": {"relationship_id": "rId7", "target": "ppt/media/image9.png", "sha256": "aa", "crop": None}},
    ]}}
    report = compare_dna(ref, cand)
    assert report.passed, "same content via different relationship IDs must pass"

    cand["slide"]["shapes"][0]["media"]["sha256"] = "bb"
    report = compare_dna(ref, cand)
    assert not report.passed
    assert report.codes.get("media.asset") == 1


def test_taxonomy_codes_cover_page_geometry_style_text_media_structure():
    ref = {
        "schema": "s",
        "page_kind": "cover",
        "slide": {
            "shapes": [
                {
                    "shape_id": "1",
                    "name": "A",
                    "z_index": 0,
                    "geometry_emu": {"x": 0, "y": 0, "cx": 10, "cy": 10, "rotation": 0.0},
                    "fill": {"type": "solid", "color": {"rgb": "000000"}},
                    "typography": {"paragraphs": [{"runs": [{"text": "hi", "font_size_pt": 12.0}]}]},
                    "media": {"sha256": "aa", "crop": {"l": 0}},
                    "custom_geometry": {"paths": [{"w": 1}]},
                },
            ]
        },
    }
    cand = {
        "schema": "s",
        "page_kind": "content",
        "slide": {
            "shapes": [
                {
                    "shape_id": "1",
                    "name": "A",
                    "z_index": 0,
                    "geometry_emu": {"x": 5, "y": 0, "cx": 10, "cy": 10, "rotation": 15.0},
                    "fill": {"type": "solid", "color": {"rgb": "FFFFFF"}},
                    "typography": {"paragraphs": [{"runs": [{"text": "hi", "font_size_pt": 18.0}]}]},
                    "media": {"sha256": "aa", "crop": {"l": 25000}},
                    "custom_geometry": {"paths": [{"w": 2}]},
                },
            ]
        },
    }
    report = compare_dna(ref, cand)
    codes = report.codes
    assert codes.get("page.page_kind")
    assert codes.get("geometry.position")
    assert codes.get("geometry.rotation")
    assert codes.get("style.fill")
    assert codes.get("text.font_size")
    assert codes.get("media.crop")
    assert codes.get("structure.custom_geometry")


def test_issue_codes_flow_into_repair_directives():
    ref = {"schema": "s", "slide": {"shapes": [
        {"shape_id": "1", "geometry_emu": {"x": 0, "y": 0, "cx": 10, "cy": 10, "rotation": 0.0}},
    ]}}
    cand = {"schema": "s", "slide": {"shapes": [
        {"shape_id": "1", "geometry_emu": {"x": 4, "y": 0, "cx": 10, "cy": 10, "rotation": 30.0}},
    ]}}
    report = compare_dna(ref, cand)
    directives = plan_from_report(report)
    operations = {d.operation for d in directives}
    assert "restore_transform" in operations  # rotation path keeps transform mapping
    assert "restore_geometry" in operations  # position path keeps geometry mapping


# --------------------------------------------------------------------------- #
# real PPTX mutation regression (extract → diff → classify)
# --------------------------------------------------------------------------- #
def _codes_for_mutation(tmp_path, mutation):
    reference = build_rich_pptx(tmp_path / "ref.pptx")
    candidate = mutate_pptx(reference, tmp_path / f"{mutation}.pptx", mutation)
    report = compare_dna(
        extract_fidelity_dna(reference, slide_index=3),
        extract_fidelity_dna(candidate, slide_index=3),
    )
    return report


def test_identity_deck_has_zero_issues(tmp_path):
    reference = build_rich_pptx(tmp_path / "ref.pptx")
    report = compare_dna(
        extract_fidelity_dna(reference, slide_index=3),
        extract_fidelity_dna(reference, slide_index=3),
    )
    assert report.passed and report.issue_count == 0


def test_real_pptx_position_change_reports_geometry_position(tmp_path):
    report = _codes_for_mutation(tmp_path, "geometry_changed")
    assert not report.passed
    assert report.codes.get("geometry.position")
    assert report.codes.get("page.page_kind") is None


def test_real_pptx_rotation_change_reports_geometry_rotation(tmp_path):
    report = _codes_for_mutation(tmp_path, "rotation_changed")
    assert report.codes.get("geometry.rotation")


def test_real_pptx_flip_change_reports_geometry_flip(tmp_path):
    report = _codes_for_mutation(tmp_path, "flip_changed")
    assert report.codes.get("geometry.flip")


def test_real_pptx_zorder_change_reports_reordered(tmp_path):
    report = _codes_for_mutation(tmp_path, "zorder_changed")
    assert report.codes.get("layer.reordered")


def test_real_pptx_crop_change_reports_media_crop(tmp_path):
    report = _codes_for_mutation(tmp_path, "crop_changed")
    assert report.codes.get("media.crop")


def test_real_pptx_font_change_reports_text_codes(tmp_path):
    report = _codes_for_mutation(tmp_path, "font_changed")
    assert report.codes.get("text.font_size") or report.codes.get("text.font")


def test_real_pptx_gradient_change_reports_style_gradient(tmp_path):
    report = _codes_for_mutation(tmp_path, "gradient_changed")
    assert report.codes.get("style.gradient")


def test_real_pptx_media_change_reports_media_asset(tmp_path):
    report = _codes_for_mutation(tmp_path, "media_changed")
    assert report.codes.get("media.asset")
