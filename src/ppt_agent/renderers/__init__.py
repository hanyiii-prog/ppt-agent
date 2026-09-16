"""Renderer SDK: pluggable IR -> artifact engines.

Register a new engine with `register_renderer`, then select it by name or let
`select_renderer` degrade from the native PPTX engine to the HTML visual engine.
"""
from __future__ import annotations

from .base import Renderer, RenderError, RenderRequest, RenderResult
from .html import HtmlRenderer, render_html_deck
from .native_pptx import NativePptxRenderer
from .registry import (
    DEFAULT_PREFERENCE,
    describe_renderers,
    get_renderer,
    preference,
    register_renderer,
    registered_names,
    render_with,
    select_renderer,
    set_preference,
    unregister_renderer,
)

__all__ = [
    "DEFAULT_PREFERENCE",
    "HtmlRenderer",
    "NativePptxRenderer",
    "RenderError",
    "RenderRequest",
    "RenderResult",
    "Renderer",
    "describe_renderers",
    "get_renderer",
    "preference",
    "register_renderer",
    "registered_names",
    "render_html_deck",
    "render_with",
    "select_renderer",
    "set_preference",
    "unregister_renderer",
]
