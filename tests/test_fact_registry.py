from ppt_agent.fact_registry import FactRegistry, audit_presentation, collect_claims
from ppt_agent.story import architect_story, story_to_ir


def test_registry_support_and_normalization():
    registry = FactRegistry()
    registry.register("完成 互联互通 上线", source_id="report.md", locator="L12")

    assert registry.is_supported("完成 互联互通 上线")
    assert registry.is_supported("  完成   互联互通   上线  ")
    assert not registry.is_supported("编造的结论")
    assert registry.unsupported(["完成 互联互通 上线", "编造的结论"]) == ["编造的结论"]
    assert len(registry) == 1


def test_registry_round_trip():
    registry = FactRegistry()
    registry.register("Fact A", source_id="s1")
    clone = FactRegistry.from_dict(registry.to_dict())
    assert clone.is_supported("fact a")
    assert len(clone) == 1


def test_collect_and_audit_presentation():
    ir = story_to_ir(architect_story("# T\n## S\n- 事实一\n- 编造二"))
    registry = FactRegistry()
    registry.register("事实一", source_id="src")

    claims = collect_claims(ir)
    assert "事实一" in claims

    report = audit_presentation(ir, registry)
    by_claim = {item["claim"]: item for item in report}
    assert by_claim["事实一"]["supported"] is True
    assert by_claim["编造二"]["supported"] is False
    assert by_claim["编造二"]["source_id"] is None
