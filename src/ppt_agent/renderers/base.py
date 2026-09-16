from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from ..ir import Presentation


class RenderError(RuntimeError):
    """Raised when a renderer cannot produce its artifact."""


@dataclass(frozen=True)
class RenderRequest:
    """Everything a renderer is allowed to know about a build."""

    output: Path
    iteration: int | None = None
    repair_requests: tuple[dict[str, Any], ...] = ()
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class RenderResult:
    renderer: str
    path: str
    slide_count: int
    editable: bool
    media_type: str = "application/octet-stream"
    capabilities: tuple[str, ...] = ()
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "renderer": self.renderer,
            "path": self.path,
            "slide_count": self.slide_count,
            "editable": self.editable,
            "media_type": self.media_type,
            "capabilities": list(self.capabilities),
            "warnings": list(self.warnings),
            "metrics": dict(self.metrics),
        }


class Renderer(ABC):
    """Stable renderer SDK.

    A renderer turns Universal IR into one build artifact. It must be
    deterministic and must not reach the network.
    """

    name: str = "renderer"
    display_name: str = "Renderer"
    media_type: str = "application/octet-stream"
    extension: str = ""
    editable: bool = False
    requires: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()

    def available(self) -> bool:
        """Whether this renderer can run in the current environment."""
        return True

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "media_type": self.media_type,
            "extension": self.extension,
            "editable": self.editable,
            "requires": list(self.requires),
            "capabilities": list(self.capabilities),
            "available": self.available(),
        }

    @abstractmethod
    def render(self, presentation: Presentation, request: RenderRequest) -> RenderResult:
        """Produce the build artifact for `presentation`."""

    def build_callback(
        self,
        presentation: Presentation,
        output: Path,
        *,
        options: Mapping[str, Any] | None = None,
    ) -> Callable[[int, list[dict[str, Any]]], Path]:
        """Adapt this renderer to the `build` callback `delivery.run_repair_loop` expects."""

        def build(iteration: int, repair_requests: list[dict[str, Any]]) -> Path:
            result = self.render(
                presentation,
                RenderRequest(
                    output=Path(output),
                    iteration=iteration,
                    repair_requests=tuple(repair_requests or ()),
                    options=dict(options or {}),
                ),
            )
            return Path(result.path)

        return build
