"""Layout engine (batch 3.D): the upgrade path inside the ONE layout algorithm.

Red line 1: ``styling.resolve_layout()`` is the only layout algorithm shared
by both renderers. This package does *not* create a second one -- it provides
the stages the solver path composes, and ``resolve_layout(..., engine="solver")``
runs them inside the single entry point. The default engine stays ``legacy``,
whose output is byte-identical to pre-V2.1 behaviour (guard-tested).

Stages
------
``typography_engine``   glyph-aware text measurement (CJK vs ASCII widths)
``image_engine``        aspect-preserving image fitting
``constraint_engine``   margin / gap / overlap / bounds violations
``layout_solver``       re-measure -> collision push-down -> grid snap ->
                        overflow shrink; deterministic, no randomness
``visual_weight``       ink/balance metrics of a resolved page
``whitespace``          whitespace ratio + margin enforcement
"""

from .constraint_engine import BoxLike, check_constraints, violations_summary
from .image_engine import fit_image
from .layout_solver import solve
from .typography_engine import measure_text_block, shrink_to_fit
from .visual_weight import page_weight
from .whitespace import enforce_margins, whitespace_ratio

__all__ = [
    "BoxLike",
    "check_constraints",
    "enforce_margins",
    "fit_image",
    "measure_text_block",
    "page_weight",
    "shrink_to_fit",
    "solve",
    "violations_summary",
    "whitespace_ratio",
]
