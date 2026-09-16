"""Text output helpers that keep generated artifacts byte-identical across platforms.

Python's text mode translates ``\\n`` to ``os.linesep`` when writing. On Windows
that silently turns every generated artifact into CRLF, so an IR file, an HTML
deck or a gate report written on Windows hashes differently from the same
artifact written on Linux. For a project whose determinism claims are checked by
hashing, that is a correctness bug rather than a cosmetic one.

Every writer of a *generated artifact* must go through here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_text_lf(path: str | Path, content: str, *, encoding: str = "utf-8") -> Path:
    """Write text with LF line endings on every platform."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding=encoding, newline="") as handle:
        handle.write(content)
    return target


def write_json_lf(
    path: str | Path,
    payload: Any,
    *,
    encoding: str = "utf-8",
    indent: int = 2,
    trailing_newline: bool = True,
) -> Path:
    """Serialise `payload` to JSON with LF endings and a stable key order."""
    text = json.dumps(payload, ensure_ascii=False, indent=indent, sort_keys=False)
    if trailing_newline:
        text += "\n"
    return write_text_lf(path, text, encoding=encoding)


def read_text(path: str | Path, *, encoding: str = "utf-8") -> str:
    """Read text with universal newlines, so LF and CRLF sources behave the same."""
    return Path(path).read_text(encoding=encoding)
