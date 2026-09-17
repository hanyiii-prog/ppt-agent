# -*- coding: utf-8 -*-
"""Data-driven clone-shell builds: a JSON page plan -> a finished, audited deck.

Why this exists
---------------
The clone route (`ppt_agent.clone_shell` + `ppt_agent.page_kits`) is a set of
Python primitives -- powerful, but a host agent driving it over MCP would have
to write Python. This module turns the route into *data*: the caller passes a
page plan (roles + kit names + plain keyword data), and every page is
dispatched to the right builder, the deck is pruned/reordered/saved, and the
result is audited before it is returned.

One call, one deck::

    render_clone_deck("template.pptx", pages=[...], output="out.pptx")

Page specs
----------
``role`` picks the builder; everything else is passed through verbatim, so
`page_kits` can grow without this module changing:

===========================  ==============================================
role                         builder
===========================  ==============================================
``cover``                    `rebuild_cover` (shell taken un-cleared so the
                             background photo survives the rebuild)
``closing``                  `rebuild_closing` (shell taken un-cleared;
                             bucket falls back to the cover pool because a
                             closing page reuses the cover shell)
``section``                  `page_kits.chapter_page` (inherits the layout's
                             rotated band)
``toc``                      `page_kits.toc_page` (bucket falls back to the
                             content pool -- a TOC is authored on the content
                             shell, which carries the chrome)
``content`` + ``kit``        `page_kits.content_header` + the named kit
===========================  ==============================================

Content-kit kwargs are exactly the `page_kits` signatures; unknown keys are
rejected by the kits themselves (TypeError surfaces as a tool error, not a
silent ignore).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .clone_shell import CloneShell, ShellExhausted, audit_pages


class CloneBuildError(ValueError):
    """A page plan this module refuses to render (bad role/kit, missing data,
    or a template with too few shells)."""


#: roles -> the shell buckets that can serve them, most specific first. A TOC
#: is authored on the *content* shell (it carries the chrome) and a closing
#: page reuses the *cover* shell -- both are template conventions, not hacks.
ROLE_BUCKETS: dict[str, tuple[str, ...]] = {
    "cover": ("cover",),
    "toc": ("toc", "content"),
    "section": ("section",),
    "content": ("content",),
    "closing": ("closing", "close", "cover"),
}

ROLES: tuple[str, ...] = tuple(ROLE_BUCKETS)

#: content kit -> its positional page_kits argument names (everything else in
#: the spec goes through as keyword arguments, title/lead/prs included).
KIT_POSITIONAL: dict[str, tuple[str, ...]] = {
    "four_role_cards": ("cards", "note"),
    "org_chart": ("top_node", "groups", "depts", "note"),
    "two_panel_list": ("left", "right"),
    "quad_cards": ("cards", "note"),
    "column_cards": ("cards",),
    "stage_cards": ("stages", "tasks"),
    "progress_timeline": ("steps", "note"),
    "stage_timeline": ("stages", "current", "note"),
}

#: content kit -> arguments that may not be None
KIT_REQUIRED: dict[str, tuple[str, ...]] = {
    "four_role_cards": ("cards",),
    "org_chart": ("top_node", "groups", "depts"),
    "two_panel_list": ("left", "right"),
    "quad_cards": ("cards",),
    "column_cards": ("cards",),
    "stage_cards": ("stages",),
    "progress_timeline": ("steps",),
    "stage_timeline": ("stages",),
}

KITS: tuple[str, ...] = tuple(KIT_POSITIONAL)

#: reserved spec keys that are consumed by this module, never forwarded
_RESERVED = frozenset({"role", "kit", "title", "lead"})


def plan_template(template: str | Path) -> dict[str, Any]:
    """Everything an agent needs to write a page plan for ``template``.

    Returns the shell inventory by role, the per-page-kind DNA counts, a
    human-readable layer-stack summary per kind (the ornaments a build must
    inherit rather than redraw) and the valid roles/kits for `render_clone_deck`.
    """
    from .page_dna import extract_deck_dna, summarize_kind

    deck = CloneShell(str(template))
    try:
        shells = deck.counts()
    finally:
        deck.close()

    dna = extract_deck_dna(template, include_raw_xml=False)
    kinds = dna.get("page_kinds") or {}
    return {
        "template": str(template),
        "shells": shells,
        "page_kind_counts": (dna.get("presentation") or {}).get("page_kind_counts"),
        "kind_summaries": {
            kind: summarize_kind(info)
            for kind, info in kinds.items()
            if info.get("count")
        },
        "roles": list(ROLES),
        "kits": list(KITS),
    }


def audit_deck(pptx: str | Path) -> dict[str, Any]:
    """Run the six-kind page audit over a finished deck."""
    from pptx import Presentation

    issues = audit_pages(Presentation(str(pptx)))
    return {"pptx": str(pptx), "count": len(issues), "issues": issues}


def _demand(pages: list[dict[str, Any]]) -> dict[str, int]:
    demand: dict[str, int] = {}
    for spec in pages:
        role = _role_of(spec)
        bucket = ROLE_BUCKETS[role][0]
        demand[bucket] = demand.get(bucket, 0) + 1
    return demand


def _role_of(spec: Any) -> str:
    if not isinstance(spec, dict):
        raise CloneBuildError(f"page spec must be an object, got {type(spec).__name__}")
    role = str(spec.get("role") or "").lower()
    if role == "close":                      # accept the shell vocabulary too
        role = "closing"
    if role not in ROLE_BUCKETS:
        raise CloneBuildError(
            f"unknown page role {role!r}; valid roles: {', '.join(ROLES)}"
        )
    return role


def _check_capacity(deck: CloneShell, pages: list[dict[str, Any]]) -> None:
    counts = deck.counts()
    problems = []
    for role in ROLE_BUCKETS:
        need = sum(1 for spec in pages if _role_of(spec) == role)
        available = sum(counts.get(bucket, 0) for bucket in ROLE_BUCKETS[role])
        if need > available:
            chain = " / ".join(ROLE_BUCKETS[role])
            problems.append(f"{role}: need {need}, template has {available} ({chain})")
    if problems:
        raise CloneBuildError(
            "template cannot serve this page plan: " + "; ".join(problems)
        )


def _take(deck: CloneShell, role: str, *, cleared: bool):
    """Take a shell from the first bucket of ``role`` that still has one."""
    last: ShellExhausted | None = None
    for bucket in ROLE_BUCKETS[role]:
        try:
            return deck.take(bucket, cleared=cleared)
        except ShellExhausted as exc:
            last = exc
    raise CloneBuildError(
        f"no shell left for role {role!r} "
        f"(buckets: {' / '.join(ROLE_BUCKETS[role])}): {last}"
    )


def _render_cover(slide: Any, spec: dict[str, Any], prs: Any) -> list[str]:
    from .clone_shell import rebuild_cover

    rebuild_cover(
        slide,
        prs=prs,
        pill_text=str(spec.get("pill") or ""),
        title_text=str(spec.get("title") or ""),
        meta_text=str(spec.get("meta") or ""),
    )
    return []


def _render_closing(slide: Any, spec: dict[str, Any], prs: Any) -> list[str]:
    from .clone_shell import rebuild_closing

    rebuild_closing(
        slide,
        prs=prs,
        title_text=str(spec.get("title") or ""),
        sub_text=str(spec.get("sub") or ""),
        meta_text=str(spec.get("meta") or ""),
    )
    return []


def _render_section(slide: Any, spec: dict[str, Any], prs: Any) -> list[str]:
    from .page_kits import chapter_page

    lines = spec.get("lines") or []
    if isinstance(lines, str):
        lines = [ln for ln in lines.split("\n") if ln.strip()]
    chapter_page(slide, str(spec.get("title") or ""), list(lines), prs=prs)
    return []


def _render_toc(slide: Any, spec: dict[str, Any], prs: Any) -> list[str]:
    from .page_kits import toc_page

    note = spec.get("note")
    if isinstance(note, str):
        note = [ln for ln in note.split("\n") if ln.strip()]
    toc_page(
        slide,
        spec.get("items") or [],
        note,
        title=str(spec.get("title") or "目录"),
        title_en=str(spec.get("title_en") or "CONTENTS"),
        prs=prs,
    )
    return []


def _render_content(slide: Any, spec: dict[str, Any], prs: Any, index: int) -> list[str]:
    from . import page_kits as K

    title = str(spec.get("title") or "")
    lead = spec.get("lead")
    kit = spec.get("kit")
    if not kit:
        K.content_header(slide, title, lead, prs=prs)
        return [f"page {index}: no 'kit' given; only the header was drawn"]
    if kit not in KIT_POSITIONAL:
        raise CloneBuildError(
            f"page {index}: unknown kit {kit!r}; valid kits: {', '.join(KITS)}"
        )
    missing = [
        key for key in KIT_REQUIRED[kit]
        if spec.get(key) is None
    ]
    if missing:
        raise CloneBuildError(
            f"page {index}: kit {kit!r} is missing required data: {', '.join(missing)}"
        )
    positional = [spec.get(key) for key in KIT_POSITIONAL[kit]]
    extra = {
        key: value for key, value in spec.items()
        if key not in _RESERVED and key not in KIT_POSITIONAL[kit]
    }
    consumed = _RESERVED | set(KIT_POSITIONAL[kit])
    ignored = sorted(set(spec) - consumed)
    fn = getattr(K, kit)
    try:
        fn(slide, *positional, title=title, lead=lead, prs=prs, **extra)
    except TypeError as exc:
        raise CloneBuildError(f"page {index}: kit {kit!r} rejected its data: {exc}") from None
    warnings = []
    if ignored:
        warnings.append(
            f"page {index}: kit {kit!r} ignored extra keys: {', '.join(ignored)}"
        )
    return warnings


def render_clone_deck(
    template: str | Path,
    pages: list[dict[str, Any]],
    output: str | Path,
    *,
    audit: bool = True,
) -> dict[str, Any]:
    """Render a page plan through the clone route and (by default) audit it.

    ``pages`` is a list of specs (see the module docstring). The output deck
    keeps one template shell per spec, in plan order, with every untouched
    decoration byte-identical to the template.
    """
    if not isinstance(pages, list) or not pages:
        raise CloneBuildError("'pages' must be a non-empty array of page specs")
    for spec in pages:
        _role_of(spec)                       # validate before opening the template

    deck = CloneShell(str(template))
    warnings: list[str] = []
    try:
        _check_capacity(deck, pages)
        for index, spec in enumerate(pages, 1):
            role = _role_of(spec)
            cleared = role not in ("cover", "closing")
            _, slide = _take(deck, role, cleared=cleared)
            if role == "cover":
                warnings.extend(_render_cover(slide, spec, deck.prs))
            elif role == "closing":
                warnings.extend(_render_closing(slide, spec, deck.prs))
            elif role == "section":
                warnings.extend(_render_section(slide, spec, deck.prs))
            elif role == "toc":
                warnings.extend(_render_toc(slide, spec, deck.prs))
            else:
                warnings.extend(_render_content(slide, spec, deck.prs, index))
        deck.finish(str(output))
    finally:
        deck.close()

    result: dict[str, Any] = {
        "output": str(output),
        "pages": len(pages),
        "shells": _demand(pages),
        "warnings": warnings,
    }
    if audit:
        result["audit"] = audit_deck(output)
    return result


__all__ = [
    "CloneBuildError",
    "KITS",
    "KIT_POSITIONAL",
    "KIT_REQUIRED",
    "ROLES",
    "ROLE_BUCKETS",
    "audit_deck",
    "plan_template",
    "render_clone_deck",
]
