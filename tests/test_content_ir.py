"""Content IR (``content-ir/v0.1``) tests."""

from __future__ import annotations

import pytest

from ppt_agent.contracts import (
    SUPPORTED_CONTENT_IR_VERSIONS,
    check_content_ir_version,
    is_content_ir_compatible,
)
from ppt_agent.content_ir import SCHEMA, ContentBlock, ContentDocument


def _doc() -> ContentDocument:
    return ContentDocument(
        source="test.md",
        format="markdown",
        title="测试文档",
        blocks=[
            ContentBlock(type="heading", id="h-0001", text="项目概况", level=2),
            ContentBlock(type="bullets", id="b-0002", items=["覆盖 5 个院区", "通过四甲评审"]),
            ContentBlock(type="table", id="tbl-0003", headers=["指标", "值"], rows=[["抽取成功率", "99.2%"]]),
        ],
    )


def test_schema_and_round_trip() -> None:
    document = _doc()
    payload = document.to_dict()
    assert payload["schema"] == "content-ir/v0.1"
    restored = ContentDocument.from_dict(payload)
    assert restored == document
    assert ContentDocument.from_json(document.to_json()) == document


def test_version_contract() -> None:
    assert tuple(SUPPORTED_CONTENT_IR_VERSIONS) == ("0.1",)
    assert check_content_ir_version(_doc().to_dict()) == "0.1"
    assert is_content_ir_compatible(_doc().to_dict())
    with pytest.raises(Exception):
        check_content_ir_version({"schema": "content-ir/v9.9"})


def test_char_volume_weights_tables() -> None:
    bullets = ContentBlock(type="bullets", id="b-1", items=["一二三四五", "六七八九十"])
    table = ContentBlock(type="table", id="t-1", headers=["a", "b"], rows=[["1", "2"]])
    assert bullets.char_volume() == 10
    assert table.char_volume() == 48  # 4 cells * 12


def test_sections_groups_children() -> None:
    document = _doc()
    sections = document.sections()
    assert len(sections) == 1
    heading, children = sections[0]
    assert heading.text == "项目概况"
    assert [block.id for block in children] == ["b-0002", "tbl-0003"]


def test_block_types_vocabulary() -> None:
    from ppt_agent.content_ir import BLOCK_TYPES

    assert set(BLOCK_TYPES) == {
        "heading", "paragraph", "bullets", "ordered", "table", "quote",
    }
