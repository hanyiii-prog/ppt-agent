"""Read bounded PDF pages as content and visual source references."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .llm.provider import ImageAttachment

MAX_REFERENCE_PDF_PAGES = 32
MAX_REFERENCE_PDF_EDGE = 1600
MAX_REFERENCE_PDF_TEXT = 24000


def _ocr_page(pixmap: Any, *, language: str) -> str:
    """Use an installed Tesseract binary when a page has no text layer."""
    executable = os.environ.get("PPT_AGENT_TESSERACT") or shutil.which("tesseract")
    if not executable and os.name == "nt":
        for candidate in (
            Path(os.environ.get("ProgramFiles", "")) / "Tesseract-OCR" / "tesseract.exe",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Tesseract-OCR" / "tesseract.exe",
        ):
            if candidate.is_file():
                executable = str(candidate)
                break
    if not executable:
        return ""
    try:
        completed = subprocess.run(
            [executable, "stdin", "stdout", "-l", language, "--psm", "6"],
            input=pixmap.tobytes("png"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=45,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.decode("utf-8", errors="replace").strip()


def extract_pdf_reference(
    path: str | Path,
    *,
    max_pages: int = MAX_REFERENCE_PDF_PAGES,
    max_chars: int = MAX_REFERENCE_PDF_TEXT,
    ocr: bool = True,
) -> dict[str, Any]:
    """Extract page-located PDF text, OCRing image-only pages when possible."""
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError("max_pages must be a positive integer")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError("max_chars must be a positive integer")

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for PDF content references") from exc

    document = pymupdf.open(source)
    try:
        page_count = len(document)
        selected_pages = list(range(1, min(page_count, max_pages) + 1))
        pages: list[dict[str, Any]] = []
        used_chars = 0
        methods: set[str] = set()
        truncated = False
        for page_number in selected_pages:
            page = document[page_number - 1]
            text = page.get_text("text").strip()
            method = "embedded_text"
            if not text and ocr:
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(2, 2),
                    alpha=False,
                    colorspace=pymupdf.csRGB,
                )
                text = _ocr_page(pixmap, language="chi_sim+eng")
                method = "ocr" if text else "unavailable"
            if not text:
                text = "[本页未能提取文字；请结合页面图像理解]"
            remaining = max_chars - used_chars
            if remaining <= 0:
                truncated = True
                break
            if len(text) > remaining:
                text = text[:remaining].rstrip()
                truncated = True
            used_chars += len(text)
            methods.add(method)
            pages.append({
                "page": page_number,
                "text": text,
                "method": method,
            })
        return {
            "page_count": page_count,
            "selected_pages": selected_pages,
            "pages": pages,
            "text_chars": used_chars,
            "methods": sorted(methods),
            "truncated": truncated or page_count > len(selected_pages),
            "ocr_available": "ocr" in methods,
        }
    finally:
        document.close()


def render_pdf_reference(
    path: str | Path,
    *,
    max_pages: int = MAX_REFERENCE_PDF_PAGES,
    max_edge: int = 1280,
) -> dict[str, Any]:
    """Render PDF pages to bounded JPEG attachments for a vision-capable model."""
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError("max_pages must be a positive integer")
    if isinstance(max_edge, bool) or not isinstance(max_edge, int) or max_edge < 256:
        raise ValueError("max_edge must be an integer of at least 256")

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)

    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for visual PDF references") from exc

    document = pymupdf.open(source)
    try:
        page_count = len(document)
        selected_pages = list(range(1, min(page_count, max_pages) + 1))
        edge_limit = min(max_edge, MAX_REFERENCE_PDF_EDGE)
        images: list[ImageAttachment] = []
        for page_number in selected_pages:
            page = document[page_number - 1]
            scale = min(1.0, edge_limit / max(page.rect.width, page.rect.height))
            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(scale, scale),
                alpha=False,
                colorspace=pymupdf.csRGB,
            )
            images.append(ImageAttachment(
                data=pixmap.tobytes("jpg", jpg_quality=82),
                mime_type="image/jpeg",
            ))
        return {
            "page_count": page_count,
            "selected_pages": selected_pages,
            "truncated": page_count > len(selected_pages),
            "images": tuple(images),
        }
    finally:
        document.close()


__all__ = [
    "MAX_REFERENCE_PDF_PAGES",
    "MAX_REFERENCE_PDF_TEXT",
    "extract_pdf_reference",
    "render_pdf_reference",
]
