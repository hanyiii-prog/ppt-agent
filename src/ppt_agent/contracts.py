from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

# --- Stable versions ------------------------------------------------------
# Every public surface (IR payloads, renderers, adapters, MCP tools, benchmark
# and release reports) is versioned here. Bump these only with a documented
# migration note in docs/release.md.
CORE_API_VERSION = "1.0"
IR_SCHEMA_VERSION = "1.0"
ADAPTER_PROTOCOL_VERSION = "1.0"
RENDERER_SDK_VERSION = "1.0"
BENCHMARK_SCHEMA_VERSION = "1.0"
RELEASE_SCHEMA_VERSION = "1.0"

# MCP protocol revisions this server can speak, newest first.
MCP_PROTOCOL_VERSIONS: tuple[str, ...] = ("2025-06-18", "2024-11-05")

# IR dialects this core can still consume. Older decks produced by V0.x carry
# version "0.1" and remain readable; new output is stamped IR_SCHEMA_VERSION.
SUPPORTED_IR_VERSIONS: tuple[str, ...] = ("0.1", IR_SCHEMA_VERSION)

# Template DNA dialects this core can still consume. Decks extracted by V2.0
# carry "template-dna/v0.4" and remain readable; the Design DNA layer
# (ppt_agent.design_dna) stamps new output "template-dna/v1.0".
TEMPLATE_DNA_SCHEMA_VERSION = "1.0"
SUPPORTED_TEMPLATE_DNA_VERSIONS: tuple[str, ...] = ("0.4", TEMPLATE_DNA_SCHEMA_VERSION)


class ContractError(ValueError):
    """Raised when an input violates a stable public contract."""


# --- Capability model -----------------------------------------------------
@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    description: str


CAPABILITY_SPECS: tuple[CapabilitySpec, ...] = (
    CapabilitySpec("filesystem", "read and write local files"),
    CapabilitySpec("shell", "execute local processes"),
    CapabilitySpec("render_preview", "rasterise slides to images for visual QA"),
    CapabilitySpec("office_automation", "drive PowerPoint/Office natively"),
    CapabilitySpec("browser", "open or inspect rendered previews"),
    CapabilitySpec("network", "reach external services"),
    CapabilitySpec("long_running", "run multi-minute jobs without a host timeout"),
)

KNOWN_CAPABILITIES: tuple[str, ...] = tuple(spec.name for spec in CAPABILITY_SPECS)

# Capabilities the core cannot work without at all.
FATAL_CAPABILITIES: tuple[str, ...] = ("filesystem",)

# capability -> (degradation code, human readable note)
FALLBACK_RULES: dict[str, tuple[str, str]] = {
    "shell": (
        "python_only",
        "no shell: external rasterisation and Office automation are unavailable",
    ),
    "render_preview": (
        "structural_gate_only",
        "no rasteriser: visual review and regression gates degrade to structural geometry checks",
    ),
    "office_automation": (
        "portable_renderer",
        "no Office automation: fall back to the portable python-pptx renderer",
    ),
    "browser": (
        "no_preview_panel",
        "no browser: HTML previews are written to disk but not opened",
    ),
    "network": (
        "offline",
        "offline: every input must resolve to a local path",
    ),
    "long_running": (
        "bounded_jobs",
        "short-lived host: keep repair loops and benchmarks bounded",
    ),
}


@dataclass(frozen=True)
class CapabilitySet:
    """An immutable set of granted capabilities."""

    granted: frozenset[str] = frozenset()

    @classmethod
    def of(cls, *names: str) -> "CapabilitySet":
        unknown = tuple(sorted(set(names) - set(KNOWN_CAPABILITIES)))
        if unknown:
            raise ContractError("unknown capability: " + ", ".join(unknown))
        return cls(frozenset(names))

    @classmethod
    def from_iterable(cls, names: Iterable[str]) -> "CapabilitySet":
        return cls.of(*tuple(names))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "CapabilitySet":
        payload = data or {}
        return cls.from_iterable(payload.get("granted") or [])

    def supports(self, name: str) -> bool:
        return name in self.granted

    def __contains__(self, name: object) -> bool:
        return name in self.granted

    def __len__(self) -> int:
        return len(self.granted)

    def missing(self, required: Iterable[str]) -> tuple[str, ...]:
        return tuple(sorted(set(required) - self.granted))

    def union(self, other: "CapabilitySet") -> "CapabilitySet":
        return CapabilitySet(self.granted | other.granted)

    def to_list(self) -> list[str]:
        return sorted(self.granted)

    def to_dict(self) -> dict[str, Any]:
        return {"granted": self.to_list()}


@dataclass(frozen=True)
class NegotiationResult:
    """Outcome of matching host capabilities against a task requirement."""

    ok: bool
    granted: tuple[str, ...]
    missing: tuple[str, ...]
    fallbacks: tuple[str, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "granted": list(self.granted),
            "missing": list(self.missing),
            "fallbacks": list(self.fallbacks),
            "notes": list(self.notes),
        }


def negotiate(
    available: CapabilitySet | Iterable[str],
    required: Iterable[str] = (),
    *,
    allow_fallback: bool = True,
) -> NegotiationResult:
    """Match required capabilities against what the host actually grants.

    Missing capabilities do not always fail the task: each documented fallback
    downgrades a gate instead of hiding it. Only FATAL_CAPABILITIES abort.
    """
    capability_set = available if isinstance(available, CapabilitySet) else CapabilitySet.from_iterable(available)
    wanted = tuple(dict.fromkeys(required))
    missing = capability_set.missing(wanted)

    fallbacks: list[str] = []
    notes: list[str] = []
    for name in missing:
        rule = FALLBACK_RULES.get(name)
        if rule is None:
            notes.append(f"{name}: missing and no documented fallback")
            continue
        fallbacks.append(rule[0])
        notes.append(f"{name}: {rule[1]}")

    fatal = tuple(name for name in missing if name in FATAL_CAPABILITIES)
    ok = not fatal and (allow_fallback or not missing)
    return NegotiationResult(
        ok=ok,
        granted=tuple(capability_set.to_list()),
        missing=missing,
        fallbacks=tuple(fallbacks),
        notes=tuple(notes),
    )


# --- IR version contract --------------------------------------------------
def ir_version_of(payload: Mapping[str, Any]) -> str:
    """Read the version of an IR payload, tolerating both stamp locations."""
    metadata = payload.get("metadata")
    meta = metadata if isinstance(metadata, Mapping) else {}
    value = payload.get("ir_version") or meta.get("ir_version") or payload.get("version")
    return str(value or "")


def check_ir_version(payload: Mapping[str, Any]) -> str:
    """Return the IR version, raising ContractError when it is absent or unsupported."""
    version = ir_version_of(payload)
    if not version:
        raise ContractError("IR payload is missing a version field")
    if version not in SUPPORTED_IR_VERSIONS:
        raise ContractError(
            f"unsupported IR version {version!r}; supported: {', '.join(SUPPORTED_IR_VERSIONS)}"
        )
    return version


def is_ir_compatible(payload: Mapping[str, Any]) -> bool:
    try:
        check_ir_version(payload)
    except ContractError:
        return False
    return True


# --- Template DNA version contract ----------------------------------------
def template_dna_version_of(payload: Mapping[str, Any]) -> str:
    """Read the template-dna version ("template-dna/v0.4" -> "0.4")."""
    schema = payload.get("schema") if isinstance(payload, Mapping) else None
    if not isinstance(schema, str) or not schema.startswith("template-dna/"):
        return ""
    return schema.split("/", 1)[1].lstrip("v")


def check_template_dna_version(payload: Mapping[str, Any]) -> str:
    """Return the template-dna version, raising ContractError when unsupported."""
    version = template_dna_version_of(payload)
    if not version:
        raise ContractError("template DNA payload is missing a 'template-dna/…' schema stamp")
    if version not in SUPPORTED_TEMPLATE_DNA_VERSIONS:
        raise ContractError(
            f"unsupported template-dna version {version!r}; "
            f"supported: {', '.join(SUPPORTED_TEMPLATE_DNA_VERSIONS)}"
        )
    return version


def is_template_dna_compatible(payload: Mapping[str, Any]) -> bool:
    try:
        check_template_dna_version(payload)
    except ContractError:
        return False
    return True


# --- Machine readable descriptor ------------------------------------------
def contract_descriptor() -> dict[str, Any]:
    """Describe every stable version and capability. Served by the MCP tool surface."""
    return {
        "core_api_version": CORE_API_VERSION,
        "ir_schema_version": IR_SCHEMA_VERSION,
        "supported_ir_versions": list(SUPPORTED_IR_VERSIONS),
        "template_dna_schema_version": TEMPLATE_DNA_SCHEMA_VERSION,
        "supported_template_dna_versions": list(SUPPORTED_TEMPLATE_DNA_VERSIONS),
        "adapter_protocol_version": ADAPTER_PROTOCOL_VERSION,
        "renderer_sdk_version": RENDERER_SDK_VERSION,
        "benchmark_schema_version": BENCHMARK_SCHEMA_VERSION,
        "release_schema_version": RELEASE_SCHEMA_VERSION,
        "mcp_protocol_versions": list(MCP_PROTOCOL_VERSIONS),
        "capabilities": [
            {"name": spec.name, "description": spec.description, "fatal": spec.name in FATAL_CAPABILITIES}
            for spec in CAPABILITY_SPECS
        ],
        "fallbacks": {
            name: {"code": rule[0], "note": rule[1]} for name, rule in sorted(FALLBACK_RULES.items())
        },
    }
