from __future__ import annotations

from typing import Any

from .deck_brief import DeckBrief
from .template_library import builtin_templates


def select_template(
    brief: DeckBrief,
    *,
    templates: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    catalog = templates or builtin_templates()
    preference = brief.template_preference
    if preference:
        if preference in catalog:
            profile = catalog[preference]
            return _with_selection(profile, 1.0, ["selected by user"], [])
        fallback = catalog["executive-briefing"]
        return _with_selection(
            fallback,
            0.0,
            [f"unknown template preference {preference!r}; fallback used"],
            [],
        )

    objective = brief.objective.lower()
    text = " ".join([brief.objective, brief.context] + brief.tone).lower()
    scored: dict[str, tuple[float, list[str]]] = {}
    for template_id, profile in catalog.items():
        score = 0.0
        reasons: list[str] = []
        for token in profile.get("scenarios", []):
            if str(token).lower() in text:
                score += 0.22
                reasons.append(f"objective matches {token}")
        for tone in brief.tone:
            if tone.lower() in {str(item).lower() for item in profile.get("tones", [])}:
                score += 0.16
                reasons.append(f"tone matches {tone}")
        if (
            any(token in objective for token in ("数据", "analysis", "compare", "comparison"))
            and "data" in profile.get("scenarios", [])
        ):
            score += 0.2
        if (
            any(token in objective for token in ("项目", "progress", "进展", "计划"))
            and "progress" in profile.get("scenarios", [])
        ):
            score += 0.2
        scored[template_id] = (min(1.0, score), reasons or ["balanced generic fit"])

    ranked = sorted(scored.items(), key=lambda item: (-item[1][0], item[0]))
    winner, (score, reasons) = ranked[0]
    fallbacks = [item[0] for item in ranked[1:3]]
    return _with_selection(catalog[winner], round(score, 3), reasons, fallbacks)


def _with_selection(
    profile: dict[str, Any],
    score: float,
    reasons: list[str],
    fallbacks: list[str],
) -> dict[str, Any]:
    return {
        **profile,
        "schema": "template-profile/v1",
        "source_kind": "builtin",
        "selection": {"score": score, "reasons": reasons, "fallbacks": fallbacks},
    }


__all__ = ["select_template"]
