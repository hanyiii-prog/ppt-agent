from pathlib import Path

import pytest

from ppt_agent.delivery import DeliveryPolicy, run_repair_loop
from ppt_agent.page_validation import DeckGateReport, PageGate


@pytest.fixture()
def tiny_deck(tmp_path: Path) -> Path:
    pptx = pytest.importorskip("pptx")
    prs = pptx.Presentation()
    prs.slides.add_slide(prs.slide_layouts[6])
    out = tmp_path / "deck.pptx"
    prs.save(out)
    return out


def test_repair_loop_rebuilds_until_page_gate_passes(tiny_deck: Path, tmp_path: Path, monkeypatch):
    calls = []

    def fake_validate(pptx, workspace, **kwargs):
        from ppt_agent.page_validation import DeckGateReport, PageGate
        from ppt_agent.visual_critic import CriticReport
        calls.append((pptx, workspace))
        passed = len(calls) >= 2
        page = PageGate(1, 1, 0, 0, 320, 180, 0.0, passed, [] if passed else ["synthetic failure"])
        return DeckGateReport(passed, 1, [page]), CriticReport(True), None

    monkeypatch.setattr("ppt_agent.delivery.validate_delivery", fake_validate)

    def build(iteration, repairs):
        assert iteration == len(calls) + 1
        if iteration == 1:
            assert repairs == []
        else:
            assert repairs and repairs[0]["page"] == 1
        return tiny_deck

    report = run_repair_loop(build, workspace=tmp_path / "work", policy=DeliveryPolicy(max_repair_iterations=3))
    assert report.passed
    assert report.iterations == 2
    assert report.attempts[0].failed_pages == [1]
    assert report.attempts[1].failed_pages == []


def test_repair_loop_blocks_delivery_after_limit(tiny_deck: Path, tmp_path: Path, monkeypatch):
    def fake_validate(pptx, workspace, **kwargs):
        from ppt_agent.page_validation import DeckGateReport, PageGate
        from ppt_agent.visual_critic import CriticReport
        page = PageGate(2, 1, 1, 0, 320, 180, 0.0, False, ["out of bounds"])
        return DeckGateReport(False, 1, [page]), CriticReport(True), None

    monkeypatch.setattr("ppt_agent.delivery.validate_delivery", fake_validate)
    report = run_repair_loop(
        lambda iteration, repairs: tiny_deck,
        workspace=tmp_path / "work",
        policy=DeliveryPolicy(max_repair_iterations=2),
    )
    assert not report.passed
    assert report.iterations == 2
    assert report.attempts[-1].failed_pages == [2]


def test_obvious_text_overflow_blocks_page_gate():
    page = PageGate(1, 1, 0, 0, 320, 180, 0.0, True, [])
    report = DeckGateReport(True, 1, [page])

    merged = __import__("ppt_agent.delivery", fromlist=["merge_layout_audit"]).merge_layout_audit(
        report,
        [{"page": 1, "kind": "overflow", "msg": "text est 2.0in > box 1.0in"}],
    )

    assert not merged.passed
    assert not merged.pages[0].passed
    assert any("layout/overflow" in issue for issue in merged.pages[0].issues)


def test_marginal_text_overflow_is_reported_without_blocking():
    page = PageGate(1, 1, 0, 0, 320, 180, 0.0, True, [])
    report = DeckGateReport(True, 1, [page])

    from ppt_agent.delivery import merge_layout_audit

    merged = merge_layout_audit(
        report,
        [{"page": 1, "kind": "overflow", "msg": "text est 1.2in > box 1.0in"}],
    )

    assert merged.passed
    assert merged.pages[0].passed
    assert merged.pages[0].layout_warnings
