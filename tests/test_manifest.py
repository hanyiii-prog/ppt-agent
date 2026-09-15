from pathlib import Path

from ppt_agent.delivery import DeliveryAttempt, DeliveryReport
from ppt_agent.manifest import build_manifest, page_role


def test_page_roles():
    assert page_role(1, 5) == "first"
    assert page_role(3, 5) == "body"
    assert page_role(5, 5) == "last"


def test_manifest_contains_every_page_and_gate_state():
    report = DeliveryReport(
        passed=False,
        iterations=1,
        final_pptx="out.pptx",
        attempts=[DeliveryAttempt(1, "out.pptx", True, True, False, [2], [])],
        page_gate={"slide_count": 2, "pages": [
            {"page": 1, "passed": True, "issues": []},
            {"page": 2, "passed": True, "issues": []},
        ]},
        critic_gate={"findings": []},
        visual_gate={"pages": [
            {"page": 1, "passed": True, "ssim": 1.0, "mae": 0.0, "mismatch_ratio": 0.0, "diff_image": None},
            {"page": 2, "passed": False, "ssim": 0.9, "mae": 0.1, "mismatch_ratio": 0.2, "diff_image": "diff/slide-2.png"},
        ]},
    )
    manifest = build_manifest(report, reference=Path("reference.pptx"))
    assert not manifest["passed"]
    assert len(manifest["pages"]) == 2
    assert manifest["pages"][0]["role"] == "first"
    assert manifest["pages"][1]["role"] == "last"
    assert manifest["pages"][1]["gates"]["visual_regression"] is False
