"""Repair layer (batch 3.E): detect -> lock-aware fix -> re-verify.

Red line 4: repairs never fake success. Every cycle reports what was applied,
what was skipped (and why -- locks, non-minimal fixes), and whether the
problem set actually shrank; an oscillating repair stops itself and says so.

Modules
-------
``problem_detection``  unify constraint violations + external findings into
                       one ``Problem`` model
``locking``            element locks the repair layer must respect
``property_repair``    attribute-level patches (font, geometry) on a box
``element_repair``     single-element fixes (overflow shrink, margin clamp)
``layout_repair``      whole-page geometry repair via the batch 3.D solver
``component_repair``   even gap distribution for card/component groups
``page_repair``        page-level reflow entry
``scheduler``          the bounded repair cycle with oscillation detection
"""

from .locking import LockSet, filter_locked
from .problem_detection import Problem, collect_problems, problems_from_constraints
from .scheduler import run_repair_cycle

__all__ = [
    "LockSet",
    "Problem",
    "collect_problems",
    "filter_locked",
    "problems_from_constraints",
    "run_repair_cycle",
]
