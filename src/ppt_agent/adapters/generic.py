from __future__ import annotations

from ..contracts import CapabilitySet
from .base import HostAdapter


class GenericAdapter(HostAdapter):
    """Filesystem-only host: the safe default when nothing else is available.

    No shell, no rasteriser, no browser. The core still runs end to end in pure
    Python; only the visual gates degrade to structural checks.
    """

    name = "generic"
    display_name = "Generic Host Adapter"
    tool_prefix = "ppt_agent"
    capabilities = CapabilitySet.of("filesystem")
    notes = (
        "no shell, rasteriser, browser or network access",
        "visual QA degrades to structural geometry gates",
    )


class LocalAdapter(HostAdapter):
    """A full local machine: filesystem, shell and LibreOffice rasterisation."""

    name = "local"
    display_name = "Local Machine Adapter"
    tool_prefix = "ppt_agent"
    capabilities = CapabilitySet.of("filesystem", "shell", "render_preview", "long_running")
    notes = (
        "rasterisation requires LibreOffice/soffice and pdftoppm on PATH",
        "long-running builds are allowed",
    )
