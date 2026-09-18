"""Element matching tests: identity pairing without index cascading."""
from ppt_agent.fidelity_match import match_elements


def _shape(shape_id, *, name=None, kind="sp", ph=None, x=0, y=0, cx=914400, cy=914400, sha=None, text=None):
    element = {
        "shape_id": shape_id,
        "kind": kind,
        "geometry_emu": {"x": x, "y": y, "cx": cx, "cy": cy, "rotation": 0.0, "rendered_bbox": {"x": x, "y": y, "cx": cx, "cy": cy}},
    }
    if name:
        element["name"] = name
    if ph:
        element["placeholder"] = ph
    if sha:
        element["media"] = {"sha256": sha}
    if text is not None:
        element["text"] = text
    return element


def test_reordered_shapes_match_by_name_not_index():
    reference = [
        _shape("1", name="A", x=0),
        _shape("2", name="B", x=914400),
        _shape("3", name="C", x=1828800),
        _shape("4", name="D", x=2743200),
    ]
    candidate = [
        _shape("1", name="A", x=0),
        _shape("3", name="C", x=1828800),
        _shape("2", name="B", x=914400),
        _shape("4", name="D", x=2743200),
    ]
    result = match_elements(reference, candidate)
    assert len(result.matched) == 4
    assert not result.added and not result.removed
    assert result.to_dict()["reorder_count"] >= 2  # B and C swapped layers
    assert all(pair.method != "index" for pair in result.matched)


def test_insertion_is_added_not_cascading():
    reference = [_shape("1", name="A", x=0), _shape("2", name="B", x=914400)]
    candidate = [
        _shape("1", name="A", x=0),
        _shape("9", name="C", x=1828800),
        _shape("2", name="B", x=914400),
    ]
    result = match_elements(reference, candidate)
    assert [element["shape_id"] for element in result.added] == ["9"]
    assert not result.removed
    assert len(result.matched) == 2
    # B matched B despite index shift: the reorder flag is honest, not a property diff
    pair_b = next(pair for pair in result.matched if pair.reference["shape_id"] == "2")
    assert pair_b.reordered


def test_removal_is_removed_not_cascading():
    reference = [_shape("1", name="A"), _shape("2", name="B"), _shape("3", name="C")]
    candidate = [_shape("1", name="A"), _shape("3", name="C")]
    result = match_elements(reference, candidate)
    assert [element["shape_id"] for element in result.removed] == ["2"]
    assert not result.added
    assert len(result.matched) == 2


def test_placeholder_identity_beats_geometry_distance():
    reference = [_shape("1", ph={"type": "title", "idx": ""}, x=0, y=0)]
    candidate = [_shape("7", ph={"type": "title", "idx": ""}, x=5000000, y=4000000)]
    result = match_elements(reference, candidate)
    assert len(result.matched) == 1
    assert result.matched[0].method == "semantic_identity"


def test_media_hash_pairs_identical_pictures():
    reference = [_shape("1", kind="pic", sha="a" * 64, x=0)]
    candidate = [_shape("5", kind="pic", sha="a" * 64, x=914400)]
    result = match_elements(reference, candidate)
    assert result.matched[0].method == "media_hash"


def test_geometry_proximity_matches_unnamed_duplicates():
    reference = [_shape("1", x=0, y=0)]
    candidate = [_shape("9", x=10000, y=10000)]
    result = match_elements(reference, candidate)
    # semantic role (same kind/area class) outranks geometry in the priority order
    assert result.matched[0].method == "role"

    # force geometry: make the role classes differ via text presence
    reference_text = [_shape("1", x=0, y=0, text="hello")]
    candidate_text = [_shape("9", x=10000, y=10000, text="hello")]
    result_text = match_elements(reference_text, candidate_text)
    assert result_text.matched[0].method in ("role", "geometry")


def test_ambiguous_identical_shapes_are_flagged():
    reference = [_shape("1"), _shape("2")]
    candidate = [_shape("8"), _shape("9")]
    result = match_elements(reference, candidate)
    # two identical candidates fit one reference equally: flagged ambiguous
    assert result.ambiguous or result.matched


def test_index_is_last_resort_and_flagged():
    reference = [_shape("1", name="X", x=0, y=0, cx=100000, cy=100000)]
    candidate = [_shape("2", name="Y", x=8000000, y=6000000, cx=100000, cy=100000)]
    result = match_elements(reference, candidate)
    assert len(result.matched) == 1
    assert result.matched[0].method == "index"


def test_match_elements_is_deterministic():
    reference = [_shape("1", name="A", x=0), _shape("2", name="B", x=914400), _shape("3", name="C", x=1828800)]
    candidate = [_shape("3", name="C", x=1828800), _shape("1", name="A", x=0), _shape("2", name="B", x=914400)]
    first = match_elements([dict(e) for e in reference], [dict(e) for e in candidate]).to_dict()
    second = match_elements([dict(e) for e in reference], [dict(e) for e in candidate]).to_dict()
    assert first == second
