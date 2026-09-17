import ppt_agent.fidelity_pipeline as pipeline


class DummyVisual:
    passed = True

    def to_dict(self):
        return {"passed": True, "pages": []}


def _invalid_pptx(tmp_path):
    path = tmp_path / "invalid.pptx"
    path.write_bytes(b"not a zip")
    return path


def test_pipeline_can_run_structural_only_without_visual_backend(tmp_path):
    path = _invalid_pptx(tmp_path)
    try:
        result = pipeline.validate_deck_fidelity(path, path, tmp_path / "work", render=False)
    except Exception as exc:
        assert isinstance(exc, (ValueError, OSError, EOFError, RuntimeError))
    else:
        assert result["visual"]["status"] == "skipped"


def test_pipeline_never_masks_structural_failure(monkeypatch, tmp_path):
    class Structural:
        passed = False
        def __getitem__(self, key):
            if key == "passed":
                return False
            raise KeyError(key)

    monkeypatch.setattr(pipeline, "compare_decks", lambda *args, **kwargs: {"passed": False, "pages": [], "package_issues": []})
    monkeypatch.setattr(pipeline, "render_and_compare", lambda *args, **kwargs: DummyVisual(), raising=False)

    # The import inside validate_deck_fidelity is intentionally lazy, so an
    # unavailable render backend is not allowed to turn structural failure
    # into success.
    result = pipeline.validate_deck_fidelity(tmp_path / "a.pptx", tmp_path / "b.pptx", tmp_path / "work")
    assert result["passed"] is False
    assert result["structural"]["passed"] is False
