"""Component repair: even gap distribution inside a card/component group."""

from __future__ import annotations

from typing import Any


def redistribute_gaps(
    boxes: list[dict[str, Any]],
    *,
    top: float,
    bottom: float,
) -> list[dict[str, Any]]:
    """Place the boxes so vertical gaps are even within [top, bottom].

    Heights are preserved; only ``y`` moves. The result keeps the input list
    order (positioning follows ascending original y). Deterministic; when the
    boxes cannot fit, the input is returned unchanged.
    """
    if len(boxes) < 2:
        return [dict(box) for box in boxes]
    order = sorted(range(len(boxes)), key=lambda index: float(boxes[index].get("y") or 0.0))
    heights = [float(boxes[index].get("h") or 0.0) for index in order]
    total_h = sum(heights)
    span = bottom - top
    if span <= 0 or total_h >= span:
        return [dict(box) for box in boxes]
    gap = (span - total_h) / (len(order) - 1)
    positioned: dict[int, float] = {}
    cursor = top
    for index, height in zip(order, heights):
        positioned[index] = round(cursor, 4)
        cursor += height + gap
    return [
        {**box, "y": positioned[index]}
        for index, box in enumerate(boxes)
    ]
