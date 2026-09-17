"""PPT Agent: portable presentation engineering primitives.

The core package imports nothing beyond the standard library. Heavy engines
(python-pptx, Pillow, numpy) are pulled in lazily by the modules that need
them, so `import ppt_agent` always succeeds.
"""

from __future__ import annotations

from typing import Any

from .contracts import (
    ADAPTER_PROTOCOL_VERSION,
    CORE_API_VERSION,
    IR_SCHEMA_VERSION,
    RENDERER_SDK_VERSION,
    SUPPORTED_IR_VERSIONS,
    CapabilitySet,
    ContractError,
    contract_descriptor,
    negotiate,
)
from .fidelity_diff import FidelityIssue, FidelityReport, assert_fidelity, compare_dna
from .fidelity_gate import assert_deck_fidelity, compare_decks

__version__ = "1.11.0"

__all__ = [
    "ADAPTER_PROTOCOL_VERSION",
    "CORE_API_VERSION",
    "CapabilitySet",
    "CloneShell",
    "dominant_colors",
    "ContractError",
    "FidelityIssue",
    "FidelityReport",
    "IR_SCHEMA_VERSION",
    "PptAgent",
    "RENDERER_SDK_VERSION",
    "SUPPORTED_IR_VERSIONS",
    "__version__",
    "assert_deck_fidelity",
    "assert_fidelity",
    "compare_decks",
    "compare_dna",
    "contract_descriptor",
    "negotiate",
]


def __getattr__(name: str) -> Any:
    """Expose the high-level SDK without importing presentation engines eagerly."""
    if name == "PptAgent":
        from .sdk import PptAgent

        return PptAgent
    if name == "dominant_colors":
        from .palette import dominant_colors

        return dominant_colors
    if name == "CloneShell":
        from .clone_shell import CloneShell

        return CloneShell
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
