"""Component Matcher: template components <-> document content.

Why this exists
---------------
Batch 1's ``component_library`` answers "what does this template reuse";
the generation layer needs "which of those reusable units does *this content*
call for". This module is that bridge -- deterministic, priority-ranked,
every match carries its reasons (no silent guesses, mirroring the
fidelity_match seven-priority spirit).

Priority ladder
---------------
P1 ``chrome``   -- components whose roles are logo/header/footer/decoration:
                   always applicable to any page of the matching kind.
P2 ``count``    -- component member count == the section's item count (the
                   classic 4-card grid matching a 4-bullet section).
P3 ``kind``     -- component carries title/body-bearing members and the
                   section has any list content (weak signal, low score).

Output is honest by construction: components that match nothing stay in
``unmatched``; every match lists which priorities fired; section hits under
score 0.5 stay unmatched rather than creating routing noise.
"""

from __future__ import annotations

from typing import Any

from .content_ir import ContentDocument

SCHEMA = "component-match/v1"

_CHROME_ROLES = frozenset({"logo", "header", "footer", "page_number", "decoration"})
_CONTENT_ROLES = frozenset({"title", "subtitle", "body", "list", "card"})


def _section_items(document: ContentDocument) -> list[dict[str, Any]]:
    """Per level>=2 section: title + list-ish item count + block ids."""
    sections: list[dict[str, Any]] = []
    for heading, children in document.sections():
        if (heading.level or 1) < 2:
            continue  # level-1 is cover material
        items: list[str] = []
        for block in children:
            if block.type in ("bullets", "ordered"):
                items.extend(block.items)
        sections.append({
            "title": heading.text or "",
            "block_ids": [block.id for block in children],
            "item_count": len(items),
        })
    return sections


def match_components(
    component_library: dict[str, Any],
    document: ContentDocument,
) -> dict[str, Any]:
    """Score every template component against every content section.

    Pure rules over the library payload (batch 1) and the document; every
    match records which priorities fired and why. Deterministic.
    """
    components = (component_library or {}).get("components") or []
    sections = _section_items(document)

    matches: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for component in components:
        roles = {
            str(member.get("semantic_role") or "unknown")
            for member in component.get("members") or []
        }
        chrome_roles = roles & _CHROME_ROLES
        content_roles = roles & _CONTENT_ROLES
        member_count = int(component.get("member_count") or 0)

        if chrome_roles:
            matches.append({
                "component_id": component.get("component_id"),
                "priority": "P1-chrome",
                "score": round(0.6 + 0.1 * len(chrome_roles), 3),
                "scope": "every-page",
                "sections": [section["title"] for section in sections] or ["*"],
                "roles": sorted(roles),
                "reasons": [
                    f"chrome role(s) {sorted(chrome_roles)}: inherited on every page",
                ],
            })
            continue

        if not content_roles:
            unmatched.append({
                "component_id": component.get("component_id"),
                "reason": "no chrome or content roles to anchor a match",
            })
            continue

        section_hits: list[dict[str, Any]] = []
        for section in sections:
            reasons: list[str] = []
            score = 0.0
            priorities: list[str] = []
            if member_count and section["item_count"] == member_count:
                score += 0.5
                priorities.append("P2-count")
                reasons.append(
                    f"member count {member_count} == section item count {section['item_count']}"
                )
            elif member_count and abs(member_count - section["item_count"]) <= 1 and section["item_count"]:
                score += 0.25
                priorities.append("P2-count~")
                reasons.append(
                    f"member count {member_count} ~= section item count {section['item_count']}"
                )
            if section["item_count"]:
                score += 0.2
                priorities.append("P3-kind")
                reasons.append("section carries list content for body-bearing members")
            if score > 0:
                section_hits.append({
                    "section": section["title"],
                    "block_ids": section["block_ids"],
                    "score": round(min(score, 0.9), 3),
                    "priorities": priorities,
                    "reasons": reasons,
                })

        # only section hits scoring >= 0.5 count as matches: a weak "~count"
        # signal alone (0.45) stays unmatched rather than creating noise
        section_hits = [hit for hit in section_hits if hit["score"] >= 0.5]
        if section_hits:
            section_hits.sort(key=lambda hit: -hit["score"])
            matches.append({
                "component_id": component.get("component_id"),
                "priority": "P2/P3-content",
                "score": section_hits[0]["score"],
                "scope": "per-section",
                "sections": [hit["section"] for hit in section_hits],
                "hits": section_hits,
                "roles": sorted(roles),
                "reasons": section_hits[0]["reasons"],
            })
        else:
            unmatched.append({
                "component_id": component.get("component_id"),
                "reason": "content component without a matching section shape",
            })

    matches.sort(key=lambda match: -match["score"])
    return {
        "schema": SCHEMA,
        "component_count": len(components),
        "matches": matches,
        "unmatched": unmatched,
        "metadata": {"matcher": "rules/priority-ladder", "llm": "off"},
    }
