"""Layout Solver: deterministic upgrade stage inside resolve_layout().

Red line 1: this solver does NOT replace ``styling.resolve_layout`` -- it is
the ``engine="solver"`` stage *inside* it. Input is the legacy-resolved box
list; output is the same list with the flow boxes improved:

1. **re-measure**  glyph-aware text heights (typography_engine) replace the
   flat chars-per-line estimate;
2. **push-down**   vertical collisions between flow boxes are resolved by
   moving the lower box down (absolute boxes never move);
3. **grid snap**   flow y/x snap onto a 0.05 in grid;
4. **overflow**    if content exceeds the bottom margin, text flow boxes
   shrink their font once (bounded by typography_engine.min) and steps 2-3
   re-run; remaining overflow is reported honestly, never hidden.

Absolute (template-injected) boxes pass through *verbatim* in every step --
their geometry is the template's own decision and is byte-identical between
engines (guard-tested).
"""

from __future__ import annotations

from typing import Any

from ..styling import LayoutBox, MARGIN_IN, text_of
from . import constraint_engine, typography_engine, visual_weight, whitespace

GRID_STEP_IN = 0.05
DEFAULT_MIN_GAP_IN = 0.08


def _snap(value: float, step: float) -> float:
    return round(round(value / step) * step, 4)


def _as_constraint_box(box: LayoutBox, index: int) -> dict[str, Any]:
    return {
        "index": index,
        "x": box.x, "y": box.y, "w": box.w, "h": box.h,
        "absolute": box.absolute,
        "font_pt": box.font_pt,
        "text": text_of(box.component),
        "type": (getattr(box.component, "type", "") or "").lower(),
    }


def _to_layout_box(box: LayoutBox, spec: dict[str, Any]) -> LayoutBox:
    return LayoutBox(
        box.component,
        float(spec["x"]), float(spec["y"]), float(spec["w"]), float(spec["h"]),
        float(spec["font_pt"]),
        bool(spec["absolute"]),
    )


def solve(
    boxes: list[LayoutBox],
    width_in: float,
    height_in: float,
    *,
    margin_in: float = MARGIN_IN,
    min_gap_in: float = DEFAULT_MIN_GAP_IN,
    grid_step_in: float = GRID_STEP_IN,
) -> tuple[list[LayoutBox], dict[str, Any]]:
    """Improve the flow boxes of an already-resolved page. Deterministic."""
    specs = [_as_constraint_box(box, index) for index, box in enumerate(boxes)]
    violations_before = constraint_engine.check_constraints(
        specs, width_in, height_in, margin_in=margin_in, min_gap_in=min_gap_in
    )

    flow = [spec for spec in specs if not spec["absolute"]]
    # 1. re-measure text heights with the glyph-aware engine
    for spec in flow:
        text = spec["text"]
        if text and spec["type"] in ("text", "paragraph", "body", "bullet", "list",
                                     "quote", "caption", "label", "heading", "title", "subtitle"):
            spec["h"] = typography_engine.measure_text_block(text, spec["w"], spec["font_pt"])

    shrunk: list[int] = []
    bottom_limit = height_in - margin_in
    top_limit = margin_in
    for _pass in range(2):
        # 2. push-down: sort flow by y, enforce min gaps; keep within margins
        flow.sort(key=lambda spec: spec["y"])
        cursor: float | None = None
        for spec in flow:
            if cursor is not None and spec["y"] < cursor + min_gap_in:
                spec["y"] = round(cursor + min_gap_in, 4)
            cursor = spec["y"] + spec["h"]
        # 3. grid snap
        for spec in flow:
            spec["y"] = _snap(max(spec["y"], top_limit), grid_step_in)
        # 4. overflow: shrink once, then re-run
        overflow = sum(
            1 for spec in flow if spec["y"] + spec["h"] > bottom_limit + 0.01
        )
        if not overflow:
            break
        if _pass == 0:
            for spec in flow:
                if not spec["text"] or spec["y"] + spec["h"] <= bottom_limit:
                    continue
                available = max(0.5, bottom_limit - spec["y"])
                new_font = typography_engine.shrink_to_fit(
                    spec["font_pt"], spec["h"], available
                )
                if new_font < spec["font_pt"]:
                    spec["font_pt"] = new_font
                    spec["h"] = typography_engine.measure_text_block(
                        spec["text"], spec["w"], new_font
                    )
                    shrunk.append(spec["index"])
        else:
            # last resort: compress gaps to fit within the page
            overflow_bottom = max(spec["y"] + spec["h"] for spec in flow) - bottom_limit
            if overflow_bottom > 0 and len(flow) >= 2:
                lift = overflow_bottom / (len(flow) - 1)
                for offset, spec in enumerate(flow[1:], start=1):
                    spec["y"] = _snap(max(top_limit, spec["y"] - lift * offset), grid_step_in)

    solved_specs = [None] * len(specs)
    for index, spec in enumerate(specs):
        solved_specs[index] = spec
    for spec in flow:
        solved_specs[spec["index"]] = spec

    solved_boxes = [_to_layout_box(boxes[spec["index"]], spec) for spec in solved_specs]
    violations_after = constraint_engine.check_constraints(
        solved_specs, width_in, height_in, margin_in=margin_in, min_gap_in=min_gap_in
    )
    box_dicts = [
        {"x": box.x, "y": box.y, "w": box.w, "h": box.h, "absolute": box.absolute}
        for box in solved_boxes
    ]
    report = {
        "engine": "solver",
        "violations_before": constraint_engine.violations_summary(violations_before),
        "violations_after": constraint_engine.violations_summary(violations_after),
        "shrunk_elements": sorted(set(shrunk)),
        "whitespace_ratio": whitespace.whitespace_ratio(box_dicts, width_in, height_in),
        "visual_weight": visual_weight.page_weight(box_dicts, width_in, height_in),
    }
    return solved_boxes, report