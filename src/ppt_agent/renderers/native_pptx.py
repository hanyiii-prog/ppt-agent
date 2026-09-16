from __future__ import annotations

import importlib.util
from pathlib import Path

from .base import Renderer, RenderError, RenderRequest, RenderResult


class NativePptxRenderer(Renderer):
    """Portable IR -> editable .pptx renderer backed by python-pptx.

    This wraps `ppt_agent.renderer.render_presentation`, the single native
    code path, so the SDK and the CLI cannot drift apart.
    """

    name = "native-pptx"
    display_name = "Native PPTX Engine"
    media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    extension = ".pptx"
    editable = True
    requires = ("python-pptx",)
    capabilities = (
        "editable",
        "deterministic",
        "absolute-placement",
        "flow-layout",
        "speaker-notes",
        "alpha-transparency",
        "group-nesting",
    )

    def available(self) -> bool:
        return importlib.util.find_spec("pptx") is not None

    def render(self, presentation, request: RenderRequest) -> RenderResult:
        if not self.available():
            raise RenderError("python-pptx is not installed; install ppt-agent[pptx]")

        from ..renderer import render_presentation

        path = Path(request.output)
        warnings: list[str] = []
        if request.repair_requests:
            warnings.append(f"{len(request.repair_requests)} repair request(s) carried into iteration {request.iteration}")
        if request.options.get("template"):
            warnings.append("template injection is not part of the native v1 renderer; use dna-to-ir first")

        written = render_presentation(presentation, path, iteration=request.iteration)
        return RenderResult(
            renderer=self.name,
            path=str(written),
            slide_count=len(presentation.slides),
            editable=True,
            media_type=self.media_type,
            capabilities=self.capabilities,
            warnings=warnings,
            metrics={"bytes": written.stat().st_size if written.exists() else 0},
        )
