"""Tests for aesthetic convergence: warning repair, convergence, contact sheet."""
from __future__ import annotations

import pytest
from PIL import Image

from ppt_agent.agent.pipeline import (
    MAX_VISUAL_ITERATIONS,
    WARNING_FIX_RULES,
    _blocking_repair_requests,
    _convergence_check,
    _finding_count,
)
from ppt_agent.deck_contact_sheet import build_contact_sheet


def _gate_report(critic_findings: list[dict], *, deck_findings: list[dict] | None = None):
    return {
        "page_gate": {"pages": [{"page": 1, "passed": True}]},
        "critic_gate": {"findings": critic_findings},
        "visual_gate": {"pages": [{"page": 1, "passed": True}]},
        "deck_gate": {"findings": deck_findings or [], "status": "reviewed"},
    }


class TestWarningRepair:
    def test_errors_always_included(self):
        report = _gate_report([
            {"page": 1, "severity": "error", "rule": "overlap", "message": "bad"},
        ])
        requests = _blocking_repair_requests(report)
        assert len(requests) == 1
        assert requests[0]["severity"] == "error"

    def test_warning_excluded_by_default(self):
        report = _gate_report([
            {"page": 2, "severity": "warning", "rule": "crowded", "message": "dense"},
        ])
        assert _blocking_repair_requests(report) == []

    def test_warning_included_when_whitelisted(self):
        report = _gate_report([
            {"page": 2, "severity": "warning", "rule": "crowded", "message": "dense"},
        ])
        requests = _blocking_repair_requests(report, include_warnings=True)
        assert len(requests) == 1
        assert requests[0]["rule"] == "crowded"
        assert requests[0]["severity"] == "warning"

    def test_open_ended_warning_not_whitelisted(self):
        report = _gate_report([
            {"page": 3, "severity": "warning", "rule": "not_polished_enough", "message": "meh"},
        ])
        assert _blocking_repair_requests(report, include_warnings=True) == []

    def test_whitelist_contains_expected_rules(self):
        for rule in ("crowded", "text_too_small", "overlap", "hierarchy", "image_text_mismatch"):
            assert rule in WARNING_FIX_RULES


class TestConvergenceCheck:
    def test_no_improvement_when_count_flat(self):
        assert _convergence_check(3, 3, 0.5, 0.5) == "no_improvement"

    def test_no_improvement_when_count_increases(self):
        assert _convergence_check(2, 4, None, None) == "no_improvement"

    def test_none_when_improving(self):
        assert _convergence_check(5, 2, 0.5, 0.6) is None

    def test_none_when_initial_count_zero(self):
        assert _convergence_check(0, 0, None, None) is None


class TestFindingCount:
    def test_counts_errors_and_fixable_warnings(self):
        report = _gate_report([
            {"page": 1, "severity": "error", "rule": "overlap", "message": ""},
            {"page": 2, "severity": "warning", "rule": "crowded", "message": ""},
            {"page": 3, "severity": "warning", "rule": "subjective", "message": ""},
        ])
        assert _finding_count(report) == 2

    def test_counts_deck_errors(self):
        report = _gate_report([], deck_findings=[
            {"page": 4, "severity": "error", "rule": "layout_repetition", "message": ""},
            {"page": 5, "severity": "warning", "rule": "density_variance", "message": ""},
        ])
        assert _finding_count(report) == 1


class TestMaxIterations:
    def test_max_is_five(self):
        assert MAX_VISUAL_ITERATIONS == 5


class TestContactSheet:
    def _png(self, path, color, size=(320, 180)):
        Image.new("RGB", size, color).save(path, format="PNG")
        return path

    def test_builds_grid(self, tmp_path):
        pages = [
            self._png(tmp_path / f"slide-{i:04d}.png", (i * 50, 0, 255 - i * 50))
            for i in range(1, 7)
        ]
        output = tmp_path / "sheet.jpg"
        result = build_contact_sheet(pages, output, cols=4)
        assert result == output
        assert output.exists()
        with Image.open(output) as sheet:
            assert sheet.width > 0 and sheet.height > 0

    def test_empty_raises(self, tmp_path):
        with pytest.raises(ValueError, match="no rendered pages"):
            build_contact_sheet([], tmp_path / "out.jpg")

    def test_labels_present(self, tmp_path):
        page = self._png(tmp_path / "slide-0001.png", (100, 100, 100))
        output = tmp_path / "sheet.jpg"
        build_contact_sheet([page], output)
        assert output.exists()
