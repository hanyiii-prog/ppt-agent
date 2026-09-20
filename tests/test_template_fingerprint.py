"""Tests for template fingerprint computation and consistency checks."""
import pytest

from ppt_agent.template_fingerprint import (
    TemplateMismatchError,
    check_template_consistency,
    compute_template_fingerprint,
)


def _make_dna(width=13.333, height=7.5, primary="1A73E8"):
    return {
        "slides": [{"slide": 1, "layers": []}],
        "presentation": {"slide_size_inches": {"width": width, "height": height}},
        "theme": {
            "colors": {"accent1": primary, "dk1": "000000"},
            "font_scheme": {
                "majorFace": {"latin": "Arial"},
                "minorFace": {"latin": "Calibri"},
            },
        },
        "masters": [{"path": "slideMaster1.xml", "shapes": [{"type": "sp"}]}],
    }


class TestComputeFingerprint:
    def test_deterministic(self):
        dna = _make_dna()
        fp1 = compute_template_fingerprint(dna)
        fp2 = compute_template_fingerprint(dna)
        assert fp1 == fp2
        assert len(fp1) == 12

    def test_different_size_different_fp(self):
        fp1 = compute_template_fingerprint(_make_dna(width=10.0))
        fp2 = compute_template_fingerprint(_make_dna(width=13.333))
        assert fp1 != fp2

    def test_different_color_different_fp(self):
        fp1 = compute_template_fingerprint(_make_dna(primary="1A73E8"))
        fp2 = compute_template_fingerprint(_make_dna(primary="FF0000"))
        assert fp1 != fp2

    def test_rejects_non_dna(self):
        with pytest.raises(ValueError):
            compute_template_fingerprint({"foo": 1})


class TestConsistency:
    def test_matching_payloads_pass(self):
        dna = _make_dna()
        dna["template_fingerprint"] = compute_template_fingerprint(dna)
        result = check_template_consistency(dna, {"template_fingerprint": dna["template_fingerprint"]})
        assert result == dna["template_fingerprint"]

    def test_mismatched_payloads_raise(self):
        with pytest.raises(TemplateMismatchError):
            check_template_consistency(
                {"template_fingerprint": "aaa111"},
                {"template_fingerprint": "bbb222"},
            )

    def test_payloads_without_fp_are_skipped(self):
        result = check_template_consistency({"foo": 1}, {"bar": 2})
        assert result == ""
