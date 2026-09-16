"""Adapter SDK: the only layer that knows about a specific agent host.

Implements capability detection and negotiation so the core never has to guess
what the surrounding platform can do. Integrators either use a declarative host
profile (`create_adapter("codex")`) or subclass `HostAdapter`.
"""
from __future__ import annotations

from .base import (
    AdapterDescription,
    CapabilityError,
    CommandResult,
    HostAdapter,
)
from .generic import GenericAdapter, LocalAdapter
from .hosts import (
    HOST_PROFILES,
    ProfileAdapter,
    create_adapter,
    describe_hosts,
    host_profile,
    list_hosts,
)

__all__ = [
    "HOST_PROFILES",
    "AdapterDescription",
    "CapabilityError",
    "CommandResult",
    "GenericAdapter",
    "HostAdapter",
    "LocalAdapter",
    "ProfileAdapter",
    "create_adapter",
    "describe_hosts",
    "host_profile",
    "list_hosts",
]


def default_adapter() -> HostAdapter:
    """The adapter used when no host is specified: the local machine."""
    return LocalAdapter()
