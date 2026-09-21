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
``section``                  `clone_shell.rebuild_section` (fills the divider
                             shell's own text in place; only `chapter_page`
                             when the shell has no box)
``toc``                      `clone_shell.rebuild_toc` (fills the shell's
                             repeated grid in place; only `toc_page` when it
                             has no grid)
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
    "section": ("section", "content"),
    "content": ("content", "section"),
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
    """Shells the plan consumes, per *bucket* (the pool depletion view)."""
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
    """Hard-fail ONLY when the template cannot supply a role at all.

    Running short on a shared pool is not fatal: ``CloneShell._take`` falls back
    to ``_duplicate_for_role`` (which clones the last used shell of that role),
    so content pages and section pages can reuse a limited set of template
    slides -- each still inherits its shell's real DNA. Rejecting the whole plan
    here because it has more pages than the template has slides was the bug that
    pushed the clone route into synthetic fallback for real decks. The only
    condition we must refuse is a role whose every bucket pool is empty, because
    duplication has nothing to clone from in that case.
    """
    counts = deck.counts()
    problems = []
    for role in ROLE_BUCKETS:
        need = sum(1 for spec in pages if _role_of(spec) == role)
        available = sum(counts.get(bucket, 0) for bucket in ROLE_BUCKETS[role])
        if need > 0 and available == 0:
            chain = " / ".join(ROLE_BUCKETS[role])
            problems.append(f"{role}: need {need}, template has 0 ({chain})")
    if problems:
        raise CloneBuildError(
            "template cannot serve this page plan: " + "; ".join(problems)
        )


def _take(deck: CloneShell, role: str, *, cleared: bool):
    """Take a shell for ``role`` -> ``(shell_index, slide, served_bucket)``.

    Prefer a fresh one from any bucket in the role's chain; when the pools are
    exhausted, duplicate the most recent shell of that role so the page still
    inherits real template DNA instead of the whole plan being rejected. The
    ``served_bucket`` lets the caller tell a page that landed on its *own* role
    shell from one that had to *borrow* a neighbour's (e.g. a TOC drawn on the
    content shell of a template with no dedicated TOC) -- only the former carries
    a checkable expected page kind.
    """
    last: ShellExhausted | None = None
    for bucket in ROLE_BUCKETS[role]:
        try:
            shell_index, slide = deck.take(bucket, cleared=cleared)
            return shell_index, slide, bucket
        except ShellExhausted as exc:
            last = exc
    # Every distinct shell in the chain is used -- clone the last one of the
    # primary bucket rather than failing. _duplicate_for_role falls back to
    # reusing any used shell (or slide 0) if this role has none of its own.
    try:
        shell_index, slide = deck._duplicate_for_role(
            ROLE_BUCKETS[role][0], cleared=cleared)
        # A duplicated shell may carry any neighbour's DNA, so its real page
        # kind is unknowable here -- return None and let the caller skip the
        # expected-kind anchor instead of pinning a false one.
        return shell_index, slide, None
    except Exception:
        raise CloneBuildError(
            f"no shell left for role {role!r} "
            f"(buckets: {' / '.join(ROLE_BUCKETS[role])}): {last}"
        ) from None


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
    """Render a divider page: edit the template shell's OWN text in place, and
    only fall back to a hand-drawn divider (with the inherited foreground) when
    the shell carries no suitable text box."""
    from .clone_shell import rebuild_section, slide_foreground

    title = str(spec.get("title") or "")
    meta = str(spec.get("meta") or spec.get("byline") or "")
    num = str(spec.get("chapter_num") or spec.get("number") or "")
    if rebuild_section(
        slide, prs=prs, title_text=title, meta_text=meta, chapter_num=num,
    ):
        return []
    # The served shell had no text boxes to write into -- this happens when a
    # content/divider bucket is exhausted and a bare shell is borrowed. Draw the
    # divider synthetically, but keep the template's own contrast colour.
    from . import page_kits as K

    lines = spec.get("lines") or spec.get("sub_points") or []
    K.chapter_page(slide, title or num, lines, prs=prs,
                   fg=slide_foreground(slide))
    return [f"section page: shell had no divider text box; drew a synthetic "
            f"divider (degraded fidelity)"]


def _render_toc(slide: Any, spec: dict[str, Any], prs: Any) -> list[str]:
    """Render a table-of-contents page: fill the shell's own repeated grid in
    place, and fall back to the synthetic TOC kit only when it has no grid."""
    from .clone_shell import rebuild_toc, slide_foreground

    if rebuild_toc(
        slide,
        prs=prs,
        items=spec.get("items") or [],
        title_text=str(spec.get("title") or ""),
        title_en=str(spec.get("title_en") or ""),
    ):
        return []
    # No TOC grid on this shell -- author the page from scratch (degraded: the
    # synthetic grid uses the deck palette, not the template's own).
    from . import page_kits as K

    K.toc_page(slide, spec.get("items") or [], spec.get("note"),
               title=str(spec.get("title") or "目录"),
               title_en=str(spec.get("title_en") or "CONTENTS"), prs=prs)
    return [f"toc page: shell had no repeated TOC grid; drew a synthetic "
            f"contents page (degraded fidelity)"]


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
    # forwarded = everything the kit actually receives; only keys that are
    # neither consumed nor forwarded are truly ignored (an unknown key that
    # reached the kit and was accepted is NOT ignored -- earlier wording
    # flagged forwarded kwargs like cols/bottom and mislead callers)
    forwarded = set(extra)
    ignored = sorted(set(spec) - consumed - forwarded)
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


def _structural_qc(pptx_path: str | Path) -> list[dict[str, Any]]:
    """Post-render structural checks that XML audit misses.

    Detects: empty text boxes, duplicate title text across shapes,
    and CJK-aware text overflow estimation per text frame.
    """
    from pptx import Presentation as _Prs
    from .clone_shell import rotated_bbox

    issues: list[dict[str, Any]] = []
    prs = _Prs(str(pptx_path))
    for pi, slide in enumerate(prs.slides, 1):
        titles: list[str] = []
        for sh in slide.shapes:
            if not sh.has_text_frame:
                continue
            text = (sh.text_frame.text or "").strip()
            # only flag TEXT_BOX shapes as empty; decorative ovals/bars are fine
            is_textbox = "TextBox" in (sh.name or "") or "TEXT_BOX" in str(sh.shape_type)
            if not text and is_textbox:
                issues.append({
                    "page": pi, "kind": "empty_textbox",
                    "msg": f"shape '{sh.name}' has no text",
                })
                continue
            # duplicate title check (same text appearing twice on a page)
            if len(text) >= 4 and text in titles:
                issues.append({
                    "page": pi, "kind": "duplicate_title",
                    "msg": f'"{text[:30]}" appears more than once on page {pi}',
                })
            if len(text) >= 4:
                titles.append(text)
            # CJK-aware overflow estimate
            try:
                L, T, W, H = rotated_bbox(sh)
            except (TypeError, ZeroDivisionError):
                continue
            if W <= 0 or H <= 0:
                continue
            cjk_count = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
            total_chars = len(text)
            if total_chars == 0:
                continue
            avg_char_w = 0.15  # inches, approximate for 14pt CJK
            chars_per_line = max(1, int(W / avg_char_w))
            est_lines = max(1, -(-total_chars // chars_per_line))
            est_height = est_lines * 0.24  # 0.24in per line at ~14pt
            if est_height > H * 1.15:
                issues.append({
                    "page": pi, "kind": "text_overflow",
                    "msg": f'estimated text height {est_height:.2f}in > box {H:.2f}in',
                })
    return issues


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
            cleared = role not in ("cover", "closing", "section", "toc")
            shell_index, slide, served_bucket = _take(deck, role, cleared=cleared)
            # the clone route keeps the TEMPLATE's page order: the shell that
            # served this spec lands at output page shell_index + 1. Anchor a
            # verifiable page kind ONLY when the shell is the role's own -- a
            # template without a divider/TOC shell legitimately serves those
            # pages from the content shell, and their DNA is the content page's;
            # expecting "section"/"toc" there would be a false fidelity failure.
            if role in verifiable and served_bucket == role:
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

    # -- structural QC: empty text, duplicate titles, overflow estimation --
    result["structural_qc"] = _structural_qc(output)

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
