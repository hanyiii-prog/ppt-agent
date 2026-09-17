from ppt_agent.fidelity_diff import FidelityIssue, compare_dna
from ppt_agent.fidelity_repair import plan_from_report, repair_plan_dict


def test_repair_plan_prioritizes_structural_repairs_and_deduplicates_paths():
    report = compare_dna(
        {"schema": "x", "page_kind": "content", "layers": [{"z_index": 1, "geometry": {"rotation": 0}}]},
        {"schema": "x", "page_kind": "section", "layers": [{"z_index": 2, "geometry": {"rotation": 5}}]},
    )
    # Inject a duplicate issue to ensure a stable plan does not repeat a path.
    report.issues.append(report.issues[-1])
    directives = plan_from_report(report)
    assert directives
    assert [d.priority for d in directives] == sorted(d.priority for d in directives)
    assert len({(d.category, d.path) for d in directives}) == len(directives)
    assert directives[0].operation == "restore_page_kind"


def test_repair_operations_map_to_high_fidelity_properties():
    issues = [
        FidelityIssue("layers[0].style.fill.alpha", "style", 1.0, 0.5, "value mismatch"),
        FidelityIssue("layers[0].geometry.rotation", "geometry", 0, 15, "value mismatch"),
        FidelityIssue("layers[0].media.source_rect.r", "media", 0, 100, "value mismatch"),
        FidelityIssue("layers[0].origin", "inheritance", "layout", "slide", "value mismatch"),
    ]
    report = type("Report", (), {"issues": issues})()
    directives = plan_from_report(report)
    assert [d.operation for d in directives] == [
        "restore_master_layout_inheritance",
        "restore_transform",
        "restore_alpha",
        "restore_media_crop",
    ]


def test_repair_plan_has_stable_serializable_schema():
    report = type("Report", (), {"issues": []})()
    payload = repair_plan_dict(report)
    assert payload == {
        "schema": "template-dna/fidelity-repair/v1",
        "issue_count": 0,
        "directive_count": 0,
        "directives": [],
    }
