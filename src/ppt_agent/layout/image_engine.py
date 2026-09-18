"""Image engine: aspect-preserving fitting for image boxes."""

from __future__ import annotations

from typing import Any


def fit_image(
    natural_w: float,
    natural_h: float,
    box_w: float,
    box_h: float,
) -> dict[str, Any]:
    """Contain-fit an image of natural size into a box; centred.

    Returns ``{"w", "h", "offset_x", "offset_y", "mode"}`` where mode is
    ``contain`` (both dims fit) or ``stretch`` (degenerate natural size).
    Never raises on zero/negative input -- degenerate sizes fall back to the
    box itself.
    """
    if natural_w <= 0 or natural_h <= 0 or box_w <= 0 or box_h <= 0:
        return {"w": box_w, "h": box_h, "offset_x": 0.0, "offset_y": 0.0, "mode": "stretch"}
    scale = min(box_w / natural_w, box_h / natural_h)
    width = round(natural_w * scale, 4)
    height = round(natural_h * scale, 4)
    return {
        "w": width,
        "h": height,
        "offset_x": round((box_w - width) / 2, 4),
        "offset_y": round((box_h - height) / 2, 4),
        "mode": "contain",
    }
