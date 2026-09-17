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


class ChromeFidelityError(ValueError):
    """A finished deck no longer carries the template's native chrome."""


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


# --------------------------------------------------------------------------- #
# Fidelity Gate for the clone route
# --------------------------------------------------------------------------- #
def _shell_layer_map(template: str | Path) -> dict[str, dict[str, Any]]:
    """Template layout/master layer inventories, keyed by part basename."""
    from .fidelity import extract_fidelity_dna

    maps: dict[str, dict[str, Any]] = {"layouts": {}, "masters": {}}
    first = extract_fidelity_dna(template, slide_index=1)
    count = first["presentation"]["slide_count"]
    for index in range(1, count + 1):
        dna = extract_fidelity_dna(template, slide_index=index)
        for kind, key in (("layout", "layouts"), ("master", "masters")):
            part = dna[kind].get("path")
            if not part:
                continue
            base = Path(part).name
            maps[key].setdefault(base, dna[kind].get("shapes", []))
    return maps


def chrome_fidelity_gate(
    template: str | Path,
    built: str | Path,
    *,
    expected_kinds: dict[int, str] | None = None,
    tolerance: float = 0.0005,
) -> dict[str, Any]:
    """Structural fidelity gate for the clone route.

    Verifies, per finished page:

    1. the page's **inherited layers** (its layout + master shapes) are
       structurally identical to the template's layers of the same parts --
       native chrome must be inherited, never redrawn or clobbered;
    2. the extracted ``page_kind`` matches ``expected_kinds`` where the caller
       anchors an expectation (the clone route keeps the *template's* page
       order, so only the caller knows which role landed on which page);
    3. TOC pages still carry a valid TOC structure fingerprint.

    The gate compares only inherited layers: the slide-local content of a
    clone is *supposed* to differ from the template shell it came from.
    Page-derived values (``stack`` / ``global_render_order`` of inherited
    shapes) are stripped before the comparison -- they legitimately vary with
    the slide content stacked above the chrome and are not chrome defects.
    """
    from .fidelity import extract_fidelity_dna
    from .fidelity_diff import compare_dna

    def _strip_derived(shapes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned = []
        for shape in shapes:
            copy = {k: v for k, v in shape.items() if k not in ("stack", "global_render_order")}
            if isinstance(copy.get("children"), list):
                copy["children"] = _strip_derived(copy["children"])
            cleaned.append(copy)
        return cleaned

    template_map = _shell_layer_map(template)
    first = extract_fidelity_dna(built, slide_index=1)
    count = first["presentation"]["slide_count"]

    pages: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        dna = extract_fidelity_dna(built, slide_index=index)
        page: dict[str, Any] = {"slide_index": index, "page_kind": dna.get("page_kind"), "passed": True, "issues": []}

        expected_kind = (expected_kinds or {}).get(index)
        if expected_kind and dna.get("page_kind") != expected_kind:
            page["issues"].append({
                "path": f"pages[{index}].page_kind",
                "code": "page.page_kind",
                "reference": expected_kind,
                "candidate": dna.get("page_kind"),
                "message": "page kind diverged from the expected kind for this page",
            })

        for kind, key in (("layout", "layouts"), ("master", "masters")):
            part = dna[kind].get("path")
            base = Path(part).name if part else ""
            reference_shapes = template_map[key].get(base)
            if reference_shapes is None:
                page["issues"].append({
                    "path": f"pages[{index}].{kind}",
                    "code": "inheritance.chrome_missing",
                    "reference": None,
                    "candidate": base,
                    "message": f"built page uses {kind} {base!r} which the template never used",
                })
                continue
            report = compare_dna(
                {"slide": {"shapes": _strip_derived(reference_shapes)}},
                {"slide": {"shapes": _strip_derived(dna[kind].get("shapes", []))}},
                tolerance=tolerance,
            )
            for issue in report.issues:
                page["issues"].append({
                    "path": f"pages[{index}].{kind}.{issue.path}",
                    "code": issue.code or issue.category,
                    "reference": issue.reference,
                    "candidate": issue.candidate,
                    "message": issue.message,
                })

        if dna.get("page_kind") == "toc":
            toc = dna.get("toc") or {}
            if not toc or not toc.get("structure_fingerprint"):
                page["issues"].append({
                    "path": f"pages[{index}].toc",
                    "code": "structure.toc_fingerprint",
                    "reference": "toc structure",
                    "candidate": None,
                    "message": "TOC page lost its structural fingerprint",
                })

        page["passed"] = not page["issues"]
        if not page["passed"]:
            issues.extend(page["issues"])
        pages.append(page)

    return {
        "schema": "template-dna/chrome-fidelity-gate/v1",
        "passed": not issues,
        "template": str(template),
        "built": str(built),
        "pages": pages,
        "issues": issues,
        "issue_count": len(issues),
    }


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
    fidelity: bool = True,
    render: bool = False,
) -> dict[str, Any]:
    """Render a page plan through the clone route and (by default) audit it.

    ``pages`` is a list of specs (see the module docstring). The output deck
    keeps one template shell per spec, in plan order, with every untouched
    decoration byte-identical to the template.

    With ``fidelity=True`` (default) the finished deck runs through the
    chrome fidelity gate: inherited layout/master layers must still match the
    template, every page kind must match its planned role, and TOC pages must
    keep their structural fingerprint. With ``render=True`` a visual status
    (``visual_pass`` / ``visual_fail`` / ``renderer_unavailable`` /
    ``renderer_error``) is appended when the structural gate passed.
    """
    if not isinstance(pages, list) or not pages:
        raise CloneBuildError("'pages' must be a non-empty array of page specs")
    for spec in pages:
        _role_of(spec)                       # validate before opening the template

    deck = CloneShell(str(template))
    warnings: list[str] = []
    # page kinds the classifier can verify *independently of page position*:
    # toc (headline text) and section (rotated band / layout tokens). cover and
    # closing are positional judgements, so a cover-shell closing page that the
    # template placed mid-deck must not be flagged.
    verifiable = ("toc", "section")
    expected_kinds: dict[int, str] = {}
    try:
        _check_capacity(deck, pages)
        for index, spec in enumerate(pages, 1):
            role = _role_of(spec)
            cleared = role not in ("cover", "closing")
            shell_index, slide = _take(deck, role, cleared=cleared)
            # the clone route keeps the TEMPLATE's page order: the shell that
            # served this spec lands at output page shell_index + 1
            if role in verifiable:
                expected_kinds[shell_index + 1] = role
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

    roles = [_role_of(spec) for spec in pages]
    if fidelity:
        gate = chrome_fidelity_gate(template, output, expected_kinds=expected_kinds or None)
        gate["planned_roles"] = roles
        result["fidelity"] = gate
        if gate["passed"] and render:
            from .visual_regression import visual_status

            result["fidelity"]["visual"] = visual_status(template, output, Path(str(output)).parent / "fidelity-visual")
    return result


__all__ = [
    "ChromeFidelityError",
    "CloneBuildError",
    "KITS",
    "KIT_POSITIONAL",
    "KIT_REQUIRED",
    "ROLES",
    "ROLE_BUCKETS",
    "audit_deck",
    "chrome_fidelity_gate",
    "plan_template",
    "render_clone_deck",
]
