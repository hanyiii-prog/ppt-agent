from __future__ import annotations

import json
import os

import pytest

pymupdf = pytest.importorskip("pymupdf")

from ppt_agent.llm.provider import ChatMessage, ImageAttachment, llm_fn_from_provider
from ppt_agent.parsers import parse_markdown
from ppt_agent.pdf_reference import extract_pdf_reference, render_pdf_reference
from ppt_agent.storyboard import build_storyboard


def _create_pdf(path, page_count: int = 3) -> None:
    document = pymupdf.open()
    for page_number in range(1, page_count + 1):
        page = document.new_page(width=595, height=842)
        page.insert_text((36, 48), f"Reference page {page_number}")
    document.save(path)
    document.close()


def test_pdf_reference_renders_bounded_numbered_page_images(tmp_path) -> None:
    source = tmp_path / "reference.pdf"
    _create_pdf(source, page_count=3)

    reference = render_pdf_reference(source, max_pages=2, max_edge=640)

    assert reference["page_count"] == 3
    assert reference["selected_pages"] == [1, 2]
    assert reference["truncated"] is True
    assert len(reference["images"]) == 2
    assert all(image.mime_type == "image/jpeg" for image in reference["images"])
    assert all(image.data.startswith(b"\xff\xd8") for image in reference["images"])


def test_pdf_reference_extracts_page_located_text_without_ocr(tmp_path) -> None:
    source = tmp_path / "text-reference.pdf"
    _create_pdf(source, page_count=2)

    reference = extract_pdf_reference(source, max_pages=1, ocr=False)

    assert reference["page_count"] == 2
    assert reference["selected_pages"] == [1]
    assert reference["pages"][0]["page"] == 1
    assert "Reference page 1" in reference["pages"][0]["text"]
    assert reference["pages"][0]["method"] == "embedded_text"


def test_pdf_reference_ocr_uses_windows_standard_install_path(tmp_path, monkeypatch) -> None:
    from ppt_agent import pdf_reference

    calls = []

    class Pixmap:
        def tobytes(self, _kind):
            return b"png"

    monkeypatch.setattr(pdf_reference.shutil, "which", lambda _name: None)
    monkeypatch.setattr(pdf_reference.os, "name", "nt")
    monkeypatch.setattr(pdf_reference.os, "environ", {
        "ProgramFiles": str(tmp_path),
        "ProgramFiles(x86)": str(tmp_path / "x86"),
    })
    executable = tmp_path / "Tesseract-OCR" / "tesseract.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"")

    def fake_run(command, **kwargs):
        calls.append(command[0])
        return type("Completed", (), {"stdout": "识别内容".encode("utf-8")})()

    monkeypatch.setattr(pdf_reference.subprocess, "run", fake_run)

    assert pdf_reference._ocr_page(Pixmap(), language="chi_sim+eng") == "识别内容"
    assert calls == [str(executable)]


def test_storyboard_attaches_pdf_images_only_through_multimodal_callable(
    tmp_path,
) -> None:
    document = parse_markdown("# Report")
    cover = document.blocks[0]
    expected = {
        "schema": "storyboard/v1",
        "slides": [{
            "kind": "cover",
            "title": "Report",
            "source_block_ids": [cover.id],
        }],
    }
    attachment = ImageAttachment(b"jpeg", "image/jpeg")
    received = {}

    class Provider:
        name = "test"
        supports_vision = True

        def chat(self, messages, **_kwargs):
            received["messages"] = messages
            return json.dumps(expected)

    llm_fn = llm_fn_from_provider(Provider())
    result = build_storyboard(
        document,
        llm_fn=llm_fn,
        constraints={"reference_pdf": {"selected_pages": [1]}},
        reference_images=[attachment],
    )

    assert result["storyboard"] is not None
    message = received["messages"][0]
    assert isinstance(message, ChatMessage)
    assert message.images == (attachment,)
