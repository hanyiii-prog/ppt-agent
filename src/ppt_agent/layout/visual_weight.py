"""Visual weight: how a resolved page distributes its ink."""

from __future__ import annotations

from typing import Any

from .constraint_engine import BoxLike, _rect


def page_weight(
    boxes: list[BoxLike],
    width_in: float,
    height_in: float,
) -> dict[str, Any]:
    """Deterministic ink metrics for one page.

    ``ink_ratio``   sum of box areas / slide area (capped at 1; overlaps may
                    double-count -- an accepted approximation, documented)
    ``top_share``   share of ink in the top half (0-1; >0.7 = top-heavy)
    ``balance``     |top_share - 0.5| scaled: 0 = perfectly balanced
    """
    slide_area = max(width_in * height_in, 1e-6)
    ink = 0.0
    top_ink = 0.0
    for box in boxes:
        _x, y, w, h = _rect(box)
        area = max(w, 0.0) * max(h, 0.0)
        ink += area
        if y + h / 2 <= height_in / 2:
            top_ink += area
    ink_ratio = min(1.0, round(ink / slide_area, 4))
    top_share = round(top_ink / ink, 4) if ink > 0 else 0.0
    return {
        "ink_ratio": ink_ratio,
        "top_share": top_share,
        "balance": round(abs(top_share - 0.5), 4),
        "top_heavy": top_share > 0.7,
    }
