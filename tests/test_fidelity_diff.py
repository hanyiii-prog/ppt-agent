from ppt_agent.fidelity_diff import assert_fidelity, compare_dna


def dna(**slide_overrides):
    payload = {
        "schema": "template-dna/v0.4",
        "page_kind": "content",
        "layers": [
            {
                "shape_id": "10",
                "z_index": 2,
                "origin": "layout",
                "geometry": {
                    "x": 100,
                    "y": 200,
                    "w": 300,
                    "h": 400,
                    "rotation": 12.0,
                    "flip_h": False,
                    "flip_v": False,
                },
                "style": {"fill": {"alpha": 0.75}, "line": {"alpha": 1.0}},
                "text": {"typeface": "Aptos", "body": {"autofit": "none"}},
                "media": {"source_rect": {"l": "0", "t": "0", "r": "0", "b": "0"}},
            },
            {"shape_id": "11", "z_index": 3, "origin": "slide"},
        ],
        "theme": {"colors": {"accent1": "FF0000"}},
        "raw_xml": "serialization-A",
    }
    payload.update(slide_overrides)
    return payload


def test_identical_dna_passes_and_ignores_raw_xml():
    reference = dna()
    candidate = dna(raw_xml="serialization-B")
    report = compare_dna(reference, candidate)
    assert report.passed
    assert report.score == 100.0
    assert report.issue_count == 0


def test_numeric_tolerance_is_applied_to_geometry():
    reference = dna()
    candidate = dna()
    candidate["layers"][0]["geometry"]["x"] = 100.0004
    assert compare_dna(reference, candidate).passed
    candidate["layers"][0]["geometry"]["x"] = 100.01
    report = compare_dna(reference, candidate)
    assert not report.passed
    assert any(i.category == "geometry" and "geometry.x" in i.path for i in report.issues)


def test_fidelity_tracks_alpha_rotation_flip_and_layer_order():
    reference = dna()
    candidate = dna()
    candidate["layers"][0]["style"]["fill"]["alpha"] = 0.50
    candidate["layers"][0]["geometry"]["rotation"] = 13.0
    candidate["layers"][0]["geometry"]["flip_h"] = True
    candidate["layers"][0], candidate["layers"][1] = candidate["layers"][1], candidate["layers"][0]
    report = compare_dna(reference, candidate)
    assert report.summary["style"] >= 1
    assert report.summary["geometry"] >= 1
    assert report.summary["layer_order"] >= 1


def test_inheritance_and_media_differences_are_classified():
    reference = dna()
    candidate = dna()
    candidate["layers"][0]["origin"] = "slide"
    candidate["layers"][0]["media"]["source_rect"]["r"] = "5000"
    report = compare_dna(reference, candidate)
    assert report.summary["inheritance"] >= 1
    assert report.summary["media"] >= 1


def test_assert_fidelity_raises_with_actionable_first_path():
    reference = dna()
    candidate = dna(page_kind="section")
    try:
        assert_fidelity(reference, candidate)
    except AssertionError as exc:
        assert "page_kind" in str(exc)
    else:
        raise AssertionError("assert_fidelity should reject a different page kind")
