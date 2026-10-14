from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TemplateLibraryEntry:
    id: str
    display_name: str
    scenarios: tuple[str, ...]
    tones: tuple[str, ...]
    primary: str
    primary_deep: str
    accent: str
    surface: str
    panel: str
    text: str
    muted: str
    inverse: str
    line: str
    title_font: str
    body_font: str
    type_scale: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "scenarios": list(self.scenarios),
            "tones": list(self.tones),
            "theme": {
                "colors": {
                    "primary": self.primary,
                    "primary_deep": self.primary_deep,
                    "accent": self.accent,
                    "surface": self.surface,
                    "panel": self.panel,
                    "text": self.text,
                    "muted": self.muted,
                    "inverse": self.inverse,
                    "line": self.line,
                },
                "fonts": {"title": self.title_font, "body": self.body_font},
                "type_scale": dict(self.type_scale),
            },
            "page_families": _page_families(self.id),
            "quality": {"validated": True, "render_status": "not_rendered"},
            "provenance": {"created_by": "ppt-agent", "license_status": "internal"},
        }


_BASE_SCALE = {
    "cover_title": 44.0,
    "title": 30.0,
    "takeaway": 20.0,
    "body": 18.0,
    "meta": 12.0,
}

_ENTRIES: tuple[TemplateLibraryEntry, ...] = (
    TemplateLibraryEntry("executive-briefing", "Executive Briefing",
        ("report", "decision", "progress", "review"), ("formal", "credible", "concise"),
        "17324B", "0E2233", "C6602D", "F4F6F8", "DDE5EC", "1F2937", "5D6D78", "FFFFFF", "B7C2CC",
        "Segoe UI", "Segoe UI", _BASE_SCALE),
    TemplateLibraryEntry("formal-enterprise", "Formal Enterprise",
        ("enterprise", "policy", "review", "governance"), ("formal", "serious", "credible"),
        "1F3864", "132947", "8496B0", "F2F5F8", "D9E2F3", "1F2937", "64748B", "FFFFFF", "BFC9D9",
        "Segoe UI", "Segoe UI", _BASE_SCALE),
    TemplateLibraryEntry("work-summary", "Work Summary",
        ("summary", "progress", "operations", "review"), ("practical", "credible", "organized"),
        "1F5F5B", "133E3B", "B4763B", "F4F7F6", "DFEAE7", "202B28", "5D6D66", "FFFFFF", "B9CBC6",
        "Segoe UI", "Segoe UI", _BASE_SCALE),
    TemplateLibraryEntry("project-progress", "Project Progress",
        ("project", "progress", "plan", "milestones"), ("practical", "credible", "concise"),
        "2E4F4F", "1D3636", "C4762C", "F5F6F5", "E0E8E5", "202B28", "5C6A66", "FFFFFF", "B4C4BF",
        "Segoe UI", "Segoe UI", _BASE_SCALE),
    TemplateLibraryEntry("consulting-strategy", "Consulting Strategy",
        ("strategy", "consulting", "analysis", "decision"), ("analytical", "credible", "structured"),
        "1F2937", "111827", "B45309", "F7F7F8", "E5E7EB", "111827", "6B7280", "FFFFFF", "D1D5DB",
        "Segoe UI", "Segoe UI", _BASE_SCALE),
    TemplateLibraryEntry("business-plan", "Business Plan",
        ("business", "plan", "growth", "market"), ("confident", "clear", "commercial"),
        "123B5C", "0D2B44", "C05A2A", "F5F7F8", "DCE7EC", "1F2937", "5C6B78", "FFFFFF", "B9C8D2",
        "Segoe UI", "Segoe UI", _BASE_SCALE),
    TemplateLibraryEntry("technology-product", "Technology Product",
        ("technology", "product", "architecture", "launch"), ("modern", "clear", "technical"),
        "173B4A", "0F2A35", "2A9D8F", "F3F7F7", "DBE8E7", "1F2937", "5D6D72", "FFFFFF", "B7C6C4",
        "Segoe UI", "Segoe UI", _BASE_SCALE),
    TemplateLibraryEntry("data-analysis", "Data Analysis",
        ("analysis", "data", "comparison", "review"), ("analytical", "credible", "precise"),
        "23505B", "133840", "B48A3C", "F5F7F7", "DFE9E8", "212B30", "5D6B6E", "FFFFFF", "AEC0BF",
        "Segoe UI", "Segoe UI", _BASE_SCALE),
    TemplateLibraryEntry("academic-research", "Academic Research",
        ("research", "academic", "method", "defense"), ("rigorous", "neutral", "credible"),
        "264653", "1B343D", "7A8C89", "F5F6F7", "DEE5E6", "212B30", "5F6C70", "FFFFFF", "B4C2C4",
        "Segoe UI", "Segoe UI", _BASE_SCALE),
    TemplateLibraryEntry("training-course", "Training Course",
        ("training", "education", "course", "guide"), ("clear", "friendly", "instructional"),
        "22577A", "173D57", "B47C3A", "F4F7F8", "DCE8EC", "202B28", "5D6D72", "FFFFFF", "B9C8D2",
        "Segoe UI", "Segoe UI", _BASE_SCALE),
    TemplateLibraryEntry("minimal-editorial", "Minimal Editorial",
        ("narrative", "proposal", "brief", "education"), ("clear", "modern", "quiet"),
        "303446", "22252F", "7C6F53", "F7F7F7", "E8E6E2", "272727", "636363", "FFFFFF", "C4C1BB",
        "Segoe UI", "Segoe UI", _BASE_SCALE),
    TemplateLibraryEntry("creative-brand", "Creative Brand",
        ("creative", "brand", "campaign", "story"), ("expressive", "modern", "bold"),
        "2D3142", "1F2230", "EF8354", "F7F7F8", "E7E7EA", "24242A", "65656D", "FFFFFF", "C7C7CE",
        "Segoe UI", "Segoe UI", _BASE_SCALE),
)


def builtin_templates() -> dict[str, dict[str, Any]]:
    return {entry.id: entry.to_dict() for entry in _ENTRIES}


def template_ids() -> list[str]:
    return [entry.id for entry in _ENTRIES]


def _page_families(template_id: str) -> list[dict[str, Any]]:
    del template_id
    return [
        {
            "id": "cover",
            "purpose_tags": ["opening", "topic"],
            "visual_forms": ["cover"],
            "density": "low",
            "slots": [
                {"id": "title", "x": 1.1, "y": 2.55, "w": 10.2, "h": 2.0,
                 "font": "cover_title", "color": "inverse", "bold": True},
                {"id": "subtitle", "x": 1.1, "y": 2.0, "w": 8.5, "h": 0.5,
                 "font": "takeaway", "color": "accent", "bold": False},
                {"id": "accent", "x": 0.0, "y": 4.9, "w": 13.333, "h": 0.09,
                 "kind": "rect", "color": "accent"},
                {"id": "background", "x": 0.0, "y": 0.0, "w": 13.333, "h": 7.5,
                 "kind": "rect", "color": "primary_deep"},
            ],
        },
        {
            "id": "content-evidence",
            "purpose_tags": ["evidence", "narrative", "list", "summary"],
            "visual_forms": ["text_evidence", "metric_group", "quote_strip"],
            "density": "standard",
            "slots": [
                {"id": "title", "x": 0.8, "y": 0.55, "w": 10.0, "h": 0.85,
                 "font": "title", "color": "primary_deep", "bold": True},
                {"id": "takeaway", "x": 0.8, "y": 1.62, "w": 11.7, "h": 0.55,
                 "font": "takeaway", "color": "primary", "bold": True},
                {"id": "body", "x": 0.8, "y": 2.4, "w": 11.7, "h": 4.2,
                 "font": "body", "color": "text", "bold": False},
                {"id": "accent", "x": 0.8, "y": 1.38, "w": 0.9, "h": 0.075,
                 "kind": "rect", "color": "accent"},
            ],
        },
        {
            "id": "content-comparison",
            "purpose_tags": ["comparison", "contrast", "matrix"],
            "visual_forms": ["comparison", "table_evidence"],
            "density": "standard",
            "slots": [
                {"id": "title", "x": 0.8, "y": 0.55, "w": 10.0, "h": 0.85,
                 "font": "title", "color": "primary_deep", "bold": True},
                {"id": "table", "x": 0.8, "y": 2.4, "w": 11.7, "h": 2.4, "kind": "table"},
                {"id": "left_panel", "x": 0.8, "y": 6.1, "w": 5.75, "h": 0.9,
                 "kind": "rect", "color": "panel"},
                {"id": "right_panel", "x": 6.75, "y": 6.1, "w": 5.75, "h": 0.9,
                 "kind": "rect", "color": "panel"},
                {"id": "left_label", "x": 1.05, "y": 6.32, "w": 5.2, "h": 0.45,
                 "font": "meta", "color": "text"},
                {"id": "right_label", "x": 7.0, "y": 6.32, "w": 5.2, "h": 0.45,
                 "font": "meta", "color": "text"},
            ],
        },
        {
            "id": "content-progress",
            "purpose_tags": ["progress", "sequence", "timeline"],
            "visual_forms": ["progress_sequence", "timeline", "flow"],
            "density": "standard",
            "slots": [
                {"id": "title", "x": 0.8, "y": 0.55, "w": 10.0, "h": 0.85,
                 "font": "title", "color": "primary_deep", "bold": True},
                {"id": "body", "x": 0.8, "y": 2.4, "w": 11.7, "h": 4.2,
                 "font": "body", "color": "text", "bold": False},
                {"id": "sequence_rule", "x": 0.8, "y": 6.7, "w": 11.7, "h": 0.03,
                 "kind": "rect", "color": "line"},
            ],
        },
        {
            "id": "closing",
            "purpose_tags": ["closing", "action"],
            "visual_forms": ["closing"],
            "density": "low",
            "slots": [
                {"id": "title", "x": 1.0, "y": 3.35, "w": 11.3, "h": 1.2,
                 "font": "cover_title", "color": "inverse", "bold": True},
                {"id": "meta", "x": 1.0, "y": 4.65, "w": 11.3, "h": 0.6,
                 "font": "meta", "color": "inverse"},
                {"id": "accent", "x": 5.97, "y": 3.05, "w": 1.4, "h": 0.09,
                 "kind": "rect", "color": "accent"},
                {"id": "background", "x": 0.0, "y": 0.0, "w": 13.333, "h": 7.5,
                 "kind": "rect", "color": "primary_deep"},
            ],
        },
    ]


__all__ = ["TemplateLibraryEntry", "builtin_templates", "template_ids"]
