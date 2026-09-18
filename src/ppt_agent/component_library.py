"""Component library: sets of elements that co-occur as one reusable unit.

Why this exists
---------------
The element library knows "the blue bar recurs 4 times"; the component
library knows "the blue bar AND the logo appear together on the same pages --
they form the template's content header". Components are what a generator
places as one decision and what a repair layer treats as one unit.

Detection (deterministic, no LLM)
---------------------------------
1. Per page, collect slide-origin element signatures (name-free, from
   ``element_library.element_signature``).
2. Count how often each signature pair co-occurs across pages.
3. Merge pairs whose co-occurrence count >= ``min_pages`` and whose
   co-occurrence covers >= ``ratio`` of both members' page sets (union-find).
4. Report groups of >= 2 signatures as components, with member roles and
   page coverage.
"""

from __future__ import annotations

from typing import Any

from .element_library import element_signature

SCHEMA = "component-library/v1"


def build_component_library(
    deck_dna: dict[str, Any],
    *,
    min_pages: int = 2,
    ratio: float = 0.7,
) -> dict[str, Any]:
    """Detect recurring co-occurrence groups among slide-origin elements."""
    pages = deck_dna.get("slides") or []
    total_pages = len(pages)

    page_sets: dict[str, set[int]] = {}
    samples: dict[str, dict[str, Any]] = {}
    for page in pages:
        slide_no = int(page.get("slide") or 0)
        for record in page.get("shapes") or []:
            key = element_signature(record)
            page_sets.setdefault(key, set()).add(slide_no)
            samples.setdefault(key, record)

    keys = [key for key, members in page_sets.items() if len(members) >= min_pages]

    # union-find over qualifying pairs
    parent: dict[str, str] = {key: key for key in keys}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, key_a in enumerate(keys):
        for key_b in keys[i + 1:]:
            shared = page_sets[key_a] & page_sets[key_b]
            if len(shared) < min_pages:
                continue
            if len(shared) / len(page_sets[key_a]) >= ratio and len(shared) / len(page_sets[key_b]) >= ratio:
                union(key_a, key_b)

    groups: dict[str, list[str]] = {}
    for key in keys:
        groups.setdefault(find(key), []).append(key)

    components: list[dict[str, Any]] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        shared_pages: set[int] = set.intersection(*(page_sets[key] for key in members))
        union_pages: set[int] = set.union(*(page_sets[key] for key in members))
        component_members = []
        for key in sorted(members):
            sample = samples[key]
            component_members.append({
                "key": key,
                "name": sample.get("name"),
                "element": sample.get("element") or sample.get("type"),
                "semantic_role": sample.get("semantic_role"),
                "geometry": sample.get("geometry"),
            })
        components.append({
            "component_id": f"comp-{len(components) + 1}",
            "member_count": len(members),
            "pages": sorted(shared_pages),
            "page_coverage": round(len(shared_pages) / total_pages, 4) if total_pages else 0.0,
            "union_pages": sorted(union_pages),
            "reuse_score": round(len(shared_pages) / total_pages, 4) if total_pages else 0.0,
            "members": component_members,
        })
    components.sort(key=lambda item: (-item["reuse_score"], -item["member_count"]))
    return {
        "schema": SCHEMA,
        "total_pages": total_pages,
        "components": components,
    }
