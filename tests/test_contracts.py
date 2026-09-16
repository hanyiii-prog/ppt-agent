import pytest

from ppt_agent.contracts import (
    CAPABILITY_SPECS,
    CORE_API_VERSION,
    IR_SCHEMA_VERSION,
    KNOWN_CAPABILITIES,
    MCP_PROTOCOL_VERSIONS,
    SUPPORTED_IR_VERSIONS,
    CapabilitySet,
    ContractError,
    check_ir_version,
    contract_descriptor,
    ir_version_of,
    is_ir_compatible,
    negotiate,
)


def test_capability_set_rejects_unknown_names():
    with pytest.raises(ContractError) as exc:
        CapabilitySet.of("filesystem", "teleportation")
    assert "teleportation" in str(exc.value)


def test_capability_set_helpers():
    granted = CapabilitySet.of("filesystem", "shell")
    assert granted.supports("shell")
    assert "filesystem" in granted
    assert granted.missing(("shell", "browser")) == ("browser",)
    assert granted.to_list() == ["filesystem", "shell"]
    assert granted.union(CapabilitySet.of("browser")).to_list() == ["browser", "filesystem", "shell"]
    assert CapabilitySet.from_dict(granted.to_dict()).to_list() == granted.to_list()
    assert CapabilitySet.from_dict(None).to_list() == []


def test_negotiation_degrades_documented_gates_instead_of_failing():
    result = negotiate(CapabilitySet.of("filesystem", "shell"), ("filesystem", "render_preview"))
    assert result.ok
    assert result.missing == ("render_preview",)
    assert result.fallbacks == ("structural_gate_only",)
    assert any("structural geometry" in note for note in result.notes)


def test_negotiation_blocks_when_a_fatal_capability_is_missing():
    result = negotiate(CapabilitySet.of("shell"), ("filesystem",))
    assert not result.ok
    assert result.missing == ("filesystem",)


def test_negotiation_can_forbid_fallbacks():
    result = negotiate(CapabilitySet.of("filesystem"), ("render_preview",), allow_fallback=False)
    assert not result.ok


def test_negotiation_reports_gaps_without_a_documented_fallback():
    # `holography` stands in for a capability a future host may require that the
    # contract has no fallback for yet: the gap is reported, not swallowed.
    result = negotiate(CapabilitySet.of("filesystem"), ("holography",))
    assert result.ok
    assert result.fallbacks == ()
    assert any("no documented fallback" in note for note in result.notes)


def test_negotiation_accepts_an_iterable_of_capabilities():
    result = negotiate(["filesystem", "shell"], ("filesystem",))
    assert result.ok
    assert result.granted == ("filesystem", "shell")


def test_ir_version_helpers():
    assert ir_version_of({"version": "0.1"}) == "0.1"
    assert ir_version_of({"ir_version": "1.0"}) == "1.0"
    assert ir_version_of({"metadata": {"ir_version": "1.0"}}) == "1.0"
    assert ir_version_of({}) == ""


def test_check_ir_version_accepts_supported_dialects():
    for version in SUPPORTED_IR_VERSIONS:
        assert check_ir_version({"version": version}) == version
    assert is_ir_compatible({"version": IR_SCHEMA_VERSION})


def test_check_ir_version_rejects_missing_and_unknown_dialects():
    with pytest.raises(ContractError):
        check_ir_version({})
    with pytest.raises(ContractError) as exc:
        check_ir_version({"version": "99.9"})
    assert "unsupported IR version" in str(exc.value)
    assert not is_ir_compatible({"version": "99.9"})


def test_contract_descriptor_is_complete_and_machine_readable():
    descriptor = contract_descriptor()
    assert descriptor["core_api_version"] == CORE_API_VERSION
    assert descriptor["ir_schema_version"] == IR_SCHEMA_VERSION
    assert descriptor["supported_ir_versions"] == list(SUPPORTED_IR_VERSIONS)
    assert descriptor["mcp_protocol_versions"] == list(MCP_PROTOCOL_VERSIONS)
    assert [item["name"] for item in descriptor["capabilities"]] == list(KNOWN_CAPABILITIES)
    assert all(spec.description for spec in CAPABILITY_SPECS)
    assert descriptor["fallbacks"]["render_preview"]["code"] == "structural_gate_only"
    assert any(item["fatal"] for item in descriptor["capabilities"])
