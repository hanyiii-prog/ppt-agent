from __future__ import annotations

from typing import Any


REQUIRED_PRESENTATION_KEYS = ("schema", "presentation", "slides", "masters", "theme")
REQUIRED_SLIDE_KEYS = ("slide", "role", "shapes")
REQUIRED_SHAPE_KEYS = ("id", "type", "geometry", "style", "fidelity")


def inspect_dna(dna: dict[str, Any]) -> dict[str, Any]:
    slides = dna.get("slides") or []
    masters = dna.get("masters") or []
    report: dict[str, Any] = {
        "schema": dna.get("schema"),
        "presentation_keys_missing": [k for k in REQUIRED_PRESENTATION_KEYS if k not in dna],
        "slide_count": len(slides),
        "master_count": len(masters),
        "roles": {},
        "shape_count": 0,
        "shape_ids": 0,
        "missing_shape_ids": 0,
        "missing_fidelity": 0,
        "missing_geometry": 0,
        "missing_style": 0,
        "group_count": 0,
        "raw_xml_count": 0,
        "alpha_transform_count": 0,
        "parent_link_count": 0,
        "issues": [],
    }
    ids: set[str] = set()
    for slide in slides:
        missing = [k for k in REQUIRED_SLIDE_KEYS if k not in slide]
        if missing:
            report["issues"].append({"slide": slide.get("slide"), "missing": missing})
        role = str(slide.get("role") or "unknown")
        report["roles"][role] = report["roles"].get(role, 0) + 1
        for shape in slide.get("shapes") or []:
            report["shape_count"] += 1
            shape_id = shape.get("id")
            if shape_id is None:
                report["missing_shape_ids"] += 1
            else:
                ids.add(str(shape_id))
                report["shape_ids"] += 1
            if "fidelity" not in shape:
                report["missing_fidelity"] += 1
            else:
                fidelity = shape.get("fidelity") or {}
                if fidelity.get("raw_xml"):
                    report["raw_xml_count"] += 1
                if fidelity.get("alpha_transforms"):
                    report["alpha_transform_count"] += 1
            if "geometry" not in shape:
                report["missing_geometry"] += 1
            if "style" not in shape:
                report["missing_style"] += 1
            if shape.get("is_group"):
                report["group_count"] += 1
            if shape.get("parent_id") is not None:
                report["parent_link_count"] += 1
    report["unique_shape_id_count"] = len(ids)
    report["duplicate_shape_id_count"] = report["shape_ids"] - len(ids)
    report["first_slide_is_first"] = bool(slides) and slides[0].get("role") == "first"
    report["last_slide_is_last"] = bool(slides) and slides[-1].get("role") == "last"
    report["ok"] = not report["presentation_keys_missing"] and not report["issues"] and report["duplicate_shape_id_count"] == 0
    return report
