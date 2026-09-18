"""End-to-end agent pipeline (batch 3.F).

``pipeline.run_pipeline`` composes every V2.1 layer over one entry point:

Input → Parse → Analyze → Narrative → Plan → Archetypes → Fidelity Mode →
Plan-to-IR (solver geometry) → Render → QA Gate → Repair Cycle → Deliver.

The report carries every stage's decision and the honest
``metadata.llm = sampled | fallback | off`` aggregate (red line 6). Clone
route stays on the clone tools; this pipeline is the designed route.
"""

from .pipeline import run_pipeline
from .plan_to_ir import plan_to_ir

__all__ = ["plan_to_ir", "run_pipeline"]
