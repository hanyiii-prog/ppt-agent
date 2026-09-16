from __future__ import annotations

from pathlib import Path

from ..ir import Presentation
from .base import Renderer, RenderError, RenderRequest, RenderResult

_REGISTRY: dict[str, Renderer] = {}

# Automatic selection order, highest fidelity first. Anything registered but
# not listed here is tried afterwards, alphabetically.
DEFAULT_PREFERENCE: tuple[str, ...] = ("native-pptx", "html")
_PREFERENCE: list[str] = list(DEFAULT_PREFERENCE)


def preference() -> tuple[str, ...]:
    return tuple(_PREFERENCE)


def set_preference(names: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Override the automatic selection order (unknown names are ignored)."""
    _PREFERENCE[:] = [name for name in names if name in _REGISTRY]
    return tuple(_PREFERENCE)


def _candidates() -> list[str]:
    preferred = [name for name in _PREFERENCE if name in _REGISTRY]
    return preferred + [name for name in registered_names() if name not in _PREFERENCE]


def register_renderer(renderer: Renderer, *, override: bool = False) -> Renderer:
    if not isinstance(renderer, Renderer):
        raise TypeError("renderer must be a Renderer instance")
    if renderer.name in _REGISTRY and not override:
        raise RenderError(f"renderer already registered: {renderer.name}")
    _REGISTRY[renderer.name] = renderer
    return renderer


def unregister_renderer(name: str) -> None:
    _REGISTRY.pop(name, None)


def registered_names() -> list[str]:
    return sorted(_REGISTRY)


def get_renderer(name: str) -> Renderer:
    try:
        return _REGISTRY[name]
    except KeyError:
        available = ", ".join(registered_names()) or "none"
        raise RenderError(f"unknown renderer {name!r}; registered: {available}") from None


def describe_renderers() -> list[dict]:
    """Renderer inventory, listed in automatic selection order."""
    return [_REGISTRY[name].describe() for name in _candidates()]


def select_renderer(
    name: str | None = None,
    *,
    editable: bool | None = None,
    require_available: bool = True,
) -> Renderer:
    """Pick a renderer, degrading from the native engine to the visual engine."""
    if name:
        renderer = get_renderer(name)
        if require_available and not renderer.available():
            requires = ", ".join(renderer.requires) or "unknown"
            raise RenderError(f"renderer {name!r} is unavailable; requires: {requires}")
        return renderer

    for candidate in _candidates():
        renderer = _REGISTRY[candidate]
        if editable is not None and renderer.editable != editable:
            continue
        if require_available and not renderer.available():
            continue
        return renderer
    raise RenderError("no registered renderer satisfies the request")


def render_with(
    presentation: Presentation,
    output: str | Path,
    *,
    renderer: str | None = None,
    editable: bool | None = None,
    iteration: int | None = None,
    repair_requests: list[dict] | None = None,
    options: dict | None = None,
) -> RenderResult:
    """Render IR through the selected renderer."""
    selected = select_renderer(renderer, editable=editable)
    return selected.render(
        presentation,
        RenderRequest(
            output=Path(output),
            iteration=iteration,
            repair_requests=tuple(repair_requests or ()),
            options=dict(options or {}),
        ),
    )


def _register_builtins() -> None:
    from .html import HtmlRenderer
    from .native_pptx import NativePptxRenderer

    # Native first: select_renderer() prefers the editable engine and falls
    # back to HTML only when python-pptx is missing.
    for renderer in (NativePptxRenderer(), HtmlRenderer()):
        if renderer.name not in _REGISTRY:
            _REGISTRY[renderer.name] = renderer


_register_builtins()
