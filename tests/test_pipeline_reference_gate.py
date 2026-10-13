"""Regression tests for the clone pipeline's reference visual gate wiring."""

from __future__ import annotations

import pytest

pytest.importorskip("pptx")


def test_pipeline_exposes_reference_gate_hook():
    from ppt_agent.agent import pipeline
    import inspect

    assert "reference_pptx" in inspect.signature(pipeline.run_pipeline).parameters


def test_pipeline_reports_only_real_rasterisers(monkeypatch):
    from ppt_agent.agent.pipeline import _detect_rasterizer

    monkeypatch.setattr("ppt_agent.render_real.real_backend", lambda: None)
    assert _detect_rasterizer() is False

    monkeypatch.setattr("ppt_agent.render_real.real_backend", lambda: "powerpoint")
    assert _detect_rasterizer() is True
