from __future__ import annotations

import json
import shutil
import subprocess
from abc import ABC
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..contracts import (
    ADAPTER_PROTOCOL_VERSION,
    CapabilitySet,
    FALLBACK_RULES,
    NegotiationResult,
    negotiate,
)


class CapabilityError(RuntimeError):
    """Raised when a host is asked for something it does not provide."""

    def __init__(self, adapter: str, capability: str, hint: str = "") -> None:
        message = f"adapter {adapter!r} does not provide the {capability!r} capability"
        if hint:
            message = f"{message}: {hint}"
        super().__init__(message)
        self.adapter = adapter
        self.capability = capability


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "returncode": self.returncode,
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


@dataclass(frozen=True)
class AdapterDescription:
    name: str
    display_name: str
    protocol_version: str
    declared: tuple[str, ...]
    effective: tuple[str, ...]
    tool_prefix: str
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "protocol_version": self.protocol_version,
            "declared": list(self.declared),
            "effective": list(self.effective),
            "tool_prefix": self.tool_prefix,
            "notes": list(self.notes),
        }


class HostAdapter(ABC):
    """Stable adapter SDK.

    A host adapter is the only place that knows how to reach a specific agent
    platform. The core never imports a host SDK; hosts implement this contract.
    """

    name: str = "generic"
    display_name: str = "Generic Host Adapter"
    tool_prefix: str = "ppt_agent"
    capabilities: CapabilitySet = CapabilitySet.of("filesystem")
    notes: tuple[str, ...] = ()

    # Capabilities that depend on the runtime, not only on the host profile.
    # `provides()` re-checks these so a claimed-but-unavailable route raises a
    # typed CapabilityError instead of failing deep inside a tool call.
    RUNTIME_GATED: frozenset[str] = frozenset({"render_preview"})

    # --- introspection ----------------------------------------------------
    def effective(self) -> CapabilitySet:
        """Capabilities actually usable right now.

        Declared capabilities are re-checked against the runtime: a host that
        claims `render_preview` on a machine without a rasteriser loses it, so
        callers degrade gates instead of crashing mid-run.
        """
        granted = set(self.capabilities.granted)
        if "render_preview" in granted:
            from ..visual_regression import rasteriser_available

            if not rasteriser_available():
                granted.discard("render_preview")
        return CapabilitySet(frozenset(granted))

    def describe(self) -> AdapterDescription:
        return AdapterDescription(
            name=self.name,
            display_name=self.display_name,
            protocol_version=ADAPTER_PROTOCOL_VERSION,
            declared=tuple(self.capabilities.to_list()),
            effective=tuple(self.effective().to_list()),
            tool_prefix=self.tool_prefix,
            notes=tuple(self.notes),
        )

    def negotiate(self, required: Iterable[str] = ()) -> NegotiationResult:
        return negotiate(self.effective(), required)

    def provides(self, capability: str) -> bool:
        """Whether a capability is usable right now."""
        if capability in self.RUNTIME_GATED:
            return capability in self.effective()
        return capability in self.capabilities

    def _hint_for(self, capability: str) -> str:
        rule = FALLBACK_RULES.get(capability)
        return rule[1] if rule else ""

    def require(self, capability: str, hint: str = "") -> None:
        if not self.provides(capability):
            raise CapabilityError(self.name, capability, hint or self._hint_for(capability))

    def check(self, required: Iterable[str] = ()) -> NegotiationResult:
        result = self.negotiate(required)
        if not result.ok:
            raise CapabilityError(
                self.name,
                ", ".join(result.missing),
                "; ".join(result.notes) or "no fallback available",
            )
        return result

    # --- filesystem -------------------------------------------------------
    def resolve_path(self, path: str | Path) -> Path:
        self.require("filesystem")
        return Path(path).expanduser().resolve()

    def ensure_dir(self, path: str | Path) -> Path:
        self.require("filesystem")
        target = Path(path).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        return target

    def read_text(self, path: str | Path, *, encoding: str = "utf-8") -> str:
        self.require("filesystem")
        return Path(path).expanduser().read_text(encoding=encoding)

    def read_json(self, path: str | Path) -> Any:
        return json.loads(self.read_text(path))

    def write_text(self, path: str | Path, content: str, *, encoding: str = "utf-8") -> Path:
        self.require("filesystem")
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding=encoding)
        return target

    def write_json(self, path: str | Path, payload: Any) -> Path:
        return self.write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    # --- shell ------------------------------------------------------------
    def which(self, executable: str) -> str | None:
        self.require("shell")
        return shutil.which(executable)

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str | Path | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        """Run a command without a shell, so arguments can never be re-parsed."""
        self.require("shell", "use the Python-only API (render_with/gate) instead")
        if isinstance(argv, (str, bytes)):
            raise TypeError("argv must be a sequence of arguments, not a shell string")
        command = [str(item) for item in argv]
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd) if cwd else None,
                timeout=timeout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except FileNotFoundError as exc:
            raise CapabilityError(self.name, "shell", f"executable not found: {command[0]}") from exc
        return CommandResult(
            argv=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout.decode("utf-8", errors="replace"),
            stderr=completed.stderr.decode("utf-8", errors="replace"),
        )

    # --- rendering routes -------------------------------------------------
    def render_preview(self, pptx: str | Path, output_dir: str | Path) -> list[str]:
        """Rasterise a deck to one PNG per slide."""
        self.require("render_preview", "visual QA degrades to structural gates instead")
        from ..visual_regression import render_pptx

        pages = render_pptx(Path(pptx), Path(output_dir))
        return [str(page) for page in pages]

    def open_preview(self, path: str | Path) -> bool:
        """Open an artifact in the host's preview surface, if it has one."""
        self.require("browser", "write the artifact to disk and let the user open it")
        return False

    def convert_with_office(self, pptx: str | Path, output_dir: str | Path, *, target: str = "pdf") -> Path:
        """Ask the host to drive PowerPoint/Office natively."""
        self.require("office_automation", "fall back to the portable python-pptx renderer")
        raise NotImplementedError(
            f"adapter {self.name!r} declares office_automation but has no converter wired up"
        )
