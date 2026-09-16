import json
from pathlib import Path

from ppt_agent.contracts import IR_SCHEMA_VERSION, SUPPORTED_IR_VERSIONS
from ppt_agent.ir import Presentation, Slide


def test_ir_schema_shape(repo_root: Path):
    schema = json.loads((repo_root / "ir" / "presentation.schema.json").read_text(encoding="utf-8"))
    assert schema["title"] == "PPT Agent Universal Presentation IR"
    assert "slides" in schema["properties"]


def test_slide_data_round_trips_into_serialized_ir():
    slide = Slide(
        id="slide-1",
        purpose="content",
        data={"role": "body", "background": {"fill": "#ffffff"}},
    )
    presentation = Presentation(version=IR_SCHEMA_VERSION, title="Demo", slides=[slide])
    payload = presentation.to_dict()
    assert payload["slides"][0]["data"]["role"] == "body"
    assert payload["slides"][0]["data"]["background"]["fill"] == "#ffffff"


def test_serialized_ir_carries_the_contract_stamp():
    presentation = Presentation(version=IR_SCHEMA_VERSION, title="Demo", slides=[Slide(id="s1", purpose="content")])
    payload = presentation.to_dict()
    assert payload["ir_version"] == IR_SCHEMA_VERSION
    assert payload["version"] == IR_SCHEMA_VERSION
    assert payload["ir_version"] in SUPPORTED_IR_VERSIONS


def test_legacy_ir_version_still_loads():
    legacy = {"version": "0.1", "metadata": {"title": "Legacy"}, "slides": [{"id": "s1", "purpose": "content"}]}
    assert Presentation.from_dict(legacy).version == "0.1"


def test_dialect_falls_back_to_the_contract_stamp():
    stamped = {"ir_version": IR_SCHEMA_VERSION, "metadata": {"title": "Stamped"}, "slides": []}
    assert Presentation.from_dict(stamped).version == IR_SCHEMA_VERSION


def test_package_version(repo_root: Path):
    import re

    import ppt_agent

    assert ppt_agent.__version__ == "1.0.0"
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version\s*=\s*"1\.0\.0"', pyproject, re.MULTILINE)


def test_importing_the_core_does_not_require_presentation_engines():
    """`import ppt_agent` must stay dependency-free."""
    import ppt_agent

    assert ppt_agent.CORE_API_VERSION
    assert "PptAgent" in ppt_agent.__all__
    assert ppt_agent.contract_descriptor()["core_api_version"] == ppt_agent.CORE_API_VERSION
