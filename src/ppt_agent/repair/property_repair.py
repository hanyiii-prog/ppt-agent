"""Property repair: attribute-level patches on a box dict.

The smallest honest repair unit: change ONE property, return a NEW dict.
Non-minimal fixes are not attempted here -- they belong to the page/element
level and must say so (mirrors fidelity_repair_executor's philosophy).
"""

from __future__ import annotations

from typing import Any

from ..layout.typography_engine import measure_text_block, shrink_to_fit

MIN_FONT_PT = 12.0


def patch_font(box: dict[str, Any], font_pt: float) -> dict[str, Any]:
    """Set a new font size; text height is re-measured immediately."""
    new_pt = round(max(MIN_FONT_PT, float(font_pt)), 1)
    patched = dict(box)
    patched["font_pt"] = new_pt
    if patched.get("text"):
        patched["h"] = measure_text_block(patched["text"], patched["w"], new_pt)
    return patched


def shrink_font_to_fit(box: dict[str, Any], available_h: float) -> tuple[dict[str, Any], bool]:
    """Shrink the box's font until its height fits ``available_h``.

    Returns (new_box, changed). Never raises; no-fit stays honest (changed=False
    is only returned when nothing changed -- a residual overflow is reported
    by the next detection round, never hidden).
    """
    needed = float(box.get("h") or 0.0)
    new_pt = shrink_to_fit(float(box.get("font_pt") or 20.0), needed, available_h)
    if new_pt >= float(box.get("font_pt") or 20.0):
        return dict(box), False
    return patch_font(box, new_pt), True


def patch_geometry(box: dict[str, Any], *, x: float | None = None, y: float | None = None,
                   w: float | None = None, h: float | None = None) -> dict[str, Any]:
    """Set one or more geometry attributes; absolute boxes are refused."""
    if box.get("absolute"):
        raise ValueError("refusing to patch geometry of an absolute (template) box")
    patched = dict(box)
    for key, value in (("x", x), ("y", y), ("w", w), ("h", h)):
        if value is not None:
            patched[key] = round(float(value), 4)
    return patched
