import json
from pathlib import Path

from ppt_agent.ir import Presentation, Slide


def test_ir_schema_shape():
    schema = json.loads(Path("ir/presentation.schema.json").read_text(encoding="utf-8"))
    assert schema["title"] == "PPT Agent Universal Presentation IR"
    assert "slides" in schema["properties"]


def test_slide_data_round_trips_into_serialized_ir():
    slide = Slide(
        id="slide-1",
        purpose="content",
        data={"role": "body", "background": {"fill": "#ffffff"}},
    )
    presentation = Presentation(version="0.1", title="Demo", slides=[slide])
    payload = presentation.to_dict()
    assert payload["slides"][0]["data"]["role"] == "body"
    assert payload["slides"][0]["data"]["background"]["fill"] == "#ffffff"


def test_package_version():
    import ppt_agent

    assert ppt_agent.__version__ == "0.1.0"
