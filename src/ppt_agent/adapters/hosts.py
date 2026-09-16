from __future__ import annotations

from typing import Any, Iterable

from ..contracts import CapabilitySet
from .base import HostAdapter

# Declarative host profiles. These are *defaults*: a profile states what the
# platform typically offers, and HostAdapter.effective() re-checks the runtime
# so a missing rasteriser cannot silently produce an empty visual gate.
HOST_PROFILES: dict[str, dict[str, Any]] = {
    "codex": {
        "display_name": "Codex",
        "capabilities": ("filesystem", "shell", "render_preview", "long_running"),
        "notes": (
            "sandboxed workspace with shell access",
            "no browser preview panel: artifacts are written to disk",
        ),
    },
    "workbuddy": {
        "display_name": "WorkBuddy",
        "capabilities": (
            "filesystem", "shell", "render_preview", "browser", "network", "long_running",
        ),
        "notes": (
            "browser preview panel and file cards are available",
            "artifacts should be returned through the host file card, not a chat bot",
        ),
    },
    "doubao": {
        "display_name": "豆包工作",
        "capabilities": ("filesystem", "shell", "render_preview", "network"),
        "notes": ("filesystem and shell available; preview depends on the client",),
    },
    "claude": {
        "display_name": "Claude",
        "capabilities": ("filesystem", "shell", "render_preview", "browser", "long_running"),
        "notes": ("local shell plus artifact preview",),
    },
    "chatgpt": {
        "display_name": "ChatGPT",
        "capabilities": ("filesystem", "shell", "network"),
        "notes": (
            "no rasteriser by default: visual gates degrade to structural checks",
        ),
    },
}


class ProfileAdapter(HostAdapter):
    """An adapter built from a declarative host profile, optionally overridden."""

    def __init__(
        self,
        name: str,
        *,
        display_name: str | None = None,
        capabilities: Iterable[str] | None = None,
        notes: Iterable[str] = (),
        tool_prefix: str | None = None,
    ) -> None:
        self.name = name
        self.display_name = display_name or name
        self.capabilities = CapabilitySet.from_iterable(capabilities or ("filesystem",))
        self.notes = tuple(notes)
        if tool_prefix:
            self.tool_prefix = tool_prefix

    def to_profile(self) -> dict[str, Any]:
        """Same shape as `AdapterDescription.to_dict()`, so one schema covers both."""
        return self.describe().to_dict()


def list_hosts() -> list[str]:
    return sorted(HOST_PROFILES)


def host_profile(host: str) -> dict[str, Any]:
    try:
        return HOST_PROFILES[host]
    except KeyError:
        available = ", ".join(list_hosts())
        raise KeyError(f"unknown host {host!r}; known hosts: {available}") from None


def create_adapter(
    host: str,
    *,
    add: Iterable[str] = (),
    remove: Iterable[str] = (),
    tool_prefix: str | None = None,
) -> ProfileAdapter:
    """Build an adapter for a known host, with optional capability overrides."""
    profile = host_profile(host)
    capabilities = set(profile.get("capabilities") or ())
    capabilities.update(add)
    capabilities.difference_update(remove)
    return ProfileAdapter(
        host,
        display_name=profile.get("display_name") or host,
        capabilities=sorted(capabilities),
        notes=profile.get("notes") or (),
        tool_prefix=tool_prefix,
    )


def describe_hosts() -> list[dict[str, Any]]:
    return [create_adapter(host).to_profile() for host in list_hosts()]
