import json
from pathlib import Path


def test_ir_schema_shape():
    schema = json.loads(Path("ir/presentation.schema.json").read_text(encoding="utf-8"))
    assert schema["title"] == "PPT Agent Universal Presentation IR"
    assert "slides" in schema["properties"]


def test_package_version():
    import ppt_agent

    assert ppt_agent.__version__ == "0.1.0"
