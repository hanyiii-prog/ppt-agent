import json
import sys
from pathlib import Path

import pytest

from ppt_agent.adapters import (
    CapabilityError,
    GenericAdapter,
    HOST_PROFILES,
    HostAdapter,
    LocalAdapter,
    create_adapter,
    describe_hosts,
    host_profile,
    list_hosts,
)
from ppt_agent.contracts import CapabilitySet


def test_generic_adapter_is_filesystem_only():
    adapter = GenericAdapter()
    assert adapter.capabilities.to_list() == ["filesystem"]
    described = adapter.describe().to_dict()
    assert described["name"] == "generic"
    assert described["protocol_version"] == "1.0"
    assert described["declared"] == ["filesystem"]
    assert described["notes"]


def test_missing_shell_raises_a_typed_capability_error():
    adapter = GenericAdapter()
    with pytest.raises(CapabilityError) as exc:
        adapter.run([sys.executable, "-c", "print(1)"])
    assert exc.value.capability == "shell"
    assert "shell" in str(exc.value)


def test_run_rejects_shell_strings():
    adapter = LocalAdapter()
    with pytest.raises(TypeError):
        adapter.run("echo hi")  # a bare string must never be re-parsed by a shell


def test_run_executes_a_command_without_a_shell():
    adapter = LocalAdapter()
    result = adapter.run([sys.executable, "-c", "print('ok')"])
    assert result.ok and result.stdout.strip() == "ok"
    assert result.to_dict()["returncode"] == 0


def test_run_reports_a_missing_executable():
    adapter = LocalAdapter()
    with pytest.raises(CapabilityError):
        adapter.run(["ppt-agent-does-not-exist-xyz"])


def test_effective_capabilities_reflect_the_runtime():
    adapter = LocalAdapter()
    from ppt_agent.visual_regression import rasteriser_available

    effective = adapter.effective()
    if rasteriser_available():
        assert effective.supports("render_preview")
    else:
        assert not effective.supports("render_preview")
        assert "render_preview" in adapter.capabilities
    assert adapter.describe().to_dict()["effective"] == effective.to_list()


def test_render_preview_refuses_without_a_rasteriser(monkeypatch, tmp_path: Path):
    adapter = LocalAdapter()
    monkeypatch.setattr("ppt_agent.visual_regression.rasteriser_available", lambda: False)
    with pytest.raises(CapabilityError):
        adapter.render_preview(tmp_path / "x.pptx", tmp_path / "pages")


def test_filesystem_round_trip(workspace: Path):
    adapter = LocalAdapter()
    target = adapter.write_json(workspace / "nested" / "fact.json", {"value": 1})
    assert target.exists()
    assert adapter.read_json(target) == {"value": 1}
    assert adapter.ensure_dir(workspace / "deep" / "dir").is_dir()
    assert adapter.resolve_path(workspace / "fact.json").name == "fact.json"


def test_check_passes_when_only_fallbacks_are_needed():
    adapter = GenericAdapter()
    result = adapter.check(("filesystem", "render_preview"))
    assert result.ok and result.fallbacks == ("structural_gate_only",)


def test_check_blocks_a_fatal_gap(monkeypatch):
    adapter = LocalAdapter()
    monkeypatch.setattr(adapter, "capabilities", CapabilitySet.of("shell"))
    with pytest.raises(CapabilityError):
        adapter.check(("filesystem",))


def test_host_profiles_are_well_formed():
    assert list_hosts() == sorted(HOST_PROFILES)
    for name in list_hosts():
        profile = host_profile(name)
        assert profile["display_name"]
        assert profile["capabilities"]
        for capability in profile["capabilities"]:
            assert capability in CapabilitySet.of(*profile["capabilities"])


def test_unknown_host_is_rejected():
    with pytest.raises(KeyError) as exc:
        create_adapter("netscape")
    assert "netscape" in str(exc.value)


def test_create_adapter_honours_add_and_remove():
    adapter = create_adapter("chatgpt", add=("render_preview",), remove=("network",))
    described = adapter.describe().to_dict()
    assert "network" not in described["declared"]
    assert "render_preview" in adapter.capabilities


def test_describe_hosts_matches_expected_hosts():
    payload = describe_hosts()
    assert {item["name"] for item in payload} == set(HOST_PROFILES)
    by_name = {item["name"]: item for item in payload}
    assert by_name["workbuddy"]["tool_prefix"] == "ppt_agent"
    assert "豆包工作" == by_name["doubao"]["display_name"]


def test_host_adapter_is_subclassable():
    class Custom(HostAdapter):
        name = "custom"
        capabilities = CapabilitySet.of("filesystem", "shell")

    adapter = Custom()
    assert adapter.describe().name == "custom"
    assert set(adapter.describe().to_dict()["effective"]) >= {"filesystem", "shell"}


def test_negotiate_is_reachable_from_an_adapter():
    result = create_adapter("chatgpt").negotiate(("filesystem", "render_preview"))
    assert result.ok
    assert result.fallbacks == ("structural_gate_only",)


def test_adapter_descriptions_are_json_serialisable():
    for adapter in (GenericAdapter(), LocalAdapter(), create_adapter("codex")):
        json.dumps(adapter.describe().to_dict(), ensure_ascii=False)
