# -*- coding: utf-8 -*-
"""clone_shell -- template-page cloning renderer for ppt-agent.

Why this exists
---------------
The DNA/theme pipeline (``template.py`` + ``dna_to_ir``) inherits *palette and
typography* from a template but re-draws every page from scratch. That loses
the template's *composition*: cover photos, freeform decorations, gradient
chips, header bars -- everything that makes a deck look "produced by the
template" rather than "a plain deck recolored to match".

This module takes the opposite route, the one that beat the gap in the
专病数据库 deck (cover colour-signature distance went 83.5 -> 6.4 vs the
template):

    1. Copy the whole template to a writable working file.
    2. Open it with python-pptx -- every slide keeps its real layout,
       master, background pictures and decorations.
    3. Classify template slides into shells by layout name
       (cover / section / content / close).
    4. For each requested page, grab one shell, ``clear_body`` it (drop every
       non-placeholder shape, keep the title placeholder), then let the
       caller inject native content.
    5. Snapshot ``sldIdLst`` children, ``drop_rel`` + remove the unused
       shells, then reorder the kept ones to match the plan.

The result is a .pptx whose untouched chrome (photos, logos, freeforms,
gradients) is byte-identical to the template -- no re-rendering, no
approximation.

API
---
``DeckPlanner`` walks the shells and hands them out; ``CloneShell`` owns the
document lifecycle.

    deck = CloneShell("template.pptx")
    shell = deck.take("content")          # -> Slide, body already cleared
    ... draw into shell ...
    deck.place_first("cover")             # pin a specific template slide
    deck.finish("out.pptx", order=[...])  # prune + reorder + save

``order`` is the list of slide indices (into the ORIGINAL template) to keep,
in final order. ``finish`` prunes everything else.
"""
from __future__ import annotations

import copy
import os
import shutil
import tempfile
from collections import Counter
from typing import Callable, Iterable, Sequence

from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN

EMU_PER_INCH = 914400.0

__all__ = ["CloneShell", "classify_shells", "clear_body", "set_title",
           "ShellExhausted", "audit_pages", "gradient_fill", "DEFAULT_ROLES",
           "set_geom", "copy_logos", "add_content_chrome", "rebuild_cover",
           "slide_foreground",
    "rebuild_section", "rebuild_toc", "rebuild_closing",
           "box", "CHROME_BAR", "CHROME_DOT1", "CHROME_DOT2",
           "set_xfrm", "shape_rot", "rotated_bbox", "clone_shape",
           "layout_chrome", "layout_placeholder_text", "drop_empty_placeholders"]

# ---------------------------------------------------------------------------
# shell classification
# ---------------------------------------------------------------------------

#: layout-name substrings -> role. First match wins; override via ``role_map``.
DEFAULT_ROLES: tuple[tuple[str, str], ...] = (
    ("章节", "section"),
    ("标题幻灯片", "cover"),       # PowerPoint's built-in title layout
    ("结尾", "close"),
    ("封底", "close"),
    ("目录", "toc"),
    ("内容", "content"),
)


def _layout_has_body_slot(layout) -> bool:
    """True when ``layout`` ships a non-title authoring placeholder.

    A *content* layout is built to be filled: it exposes a body / content
    placeholder (``idx != 0``) that authors click into. Divider, section and
    table-of-contents layouts are hand-composed decorations with no such slot.
    This is a structural signal -- it holds for any template without matching a
    single literal string, and it is what the layout-name tokens below cannot
    express for templates whose layouts are named ``1_导航页版式`` etc.
    """
    for sh in getattr(layout, "shapes", ()):
        try:
            if sh.is_placeholder and int(sh.placeholder_format.idx) != 0:
                return True
        except (AttributeError, ValueError, TypeError):
            continue
    return False


def _repeated_field_count(slide) -> int:
    """Largest cluster of same-font-size text boxes on ``slide``.

    A table of contents is the one hand-composed page that repeats a *list* of
    equal fields -- several chapter titles at one size, several index numbers at
    another. A section divider carries a single heading instead, so every size
    appears once. The biggest repeat count therefore reads >=2 for a TOC and 1
    for a divider, without matching any text or layout-name literal.
    """
    sizes: list[int] = []
    for sh in _iter_text_shapes(slide):
        pt = _font_size_pt(sh)
        if pt:
            sizes.append(int(round(pt)))
    if not sizes:
        return 0
    return max(Counter(sizes).values())


def classify_shells(prs: Presentation,
                    role_map: Sequence[tuple[str, str]] = DEFAULT_ROLES
                    ) -> dict[str, list[int]]:
    """Bucket slide indices by role.

    Two passes, both literal-free where the layout name is unhelpful:

    1. *Name* -- match ``role_map`` substrings (``章节`` / ``目录`` / ...).
    2. *Structure* -- layouts whose name matches nothing are content when they
       carry an authoring body slot, otherwise decorative; the single decorative
       layout with a repeated title cluster is the table of contents and the
       remaining decorative layouts are section dividers.
    """
    slides = list(prs.slides)
    buckets: dict[str, list[int]] = {}
    unmatched: list[int] = []                      # slide idx whose name told us nothing
    for i, slide in enumerate(slides):
        name = slide.slide_layout.name or ""
        for key, r in role_map:
            if key in name:
                buckets.setdefault(r, []).append(i)
                break
        else:
            unmatched.append(i)

    # structural fallback: split unmatched layouts into content vs decorative
    content_idxs: list[int] = []
    decor_by_layout: dict[int, list[int]] = {}     # layout id -> slide idxs
    for i in unmatched:
        layout = slides[i].slide_layout
        if _layout_has_body_slot(layout):
            content_idxs.append(i)
        else:
            decor_by_layout.setdefault(id(layout), []).append(i)

    buckets.setdefault("content", []).extend(content_idxs)

    # Among decorative layouts, the one whose slides repeat equal-font fields
    # (a list of chapter titles / index numbers) is the table of contents; the
    # rest are section dividers. Highest repeat wins so a deck with a single
    # decorative layout never invents a TOC from a lone divider.
    def _score(lid: int) -> int:
        idxs = decor_by_layout[lid]
        return max(_repeated_field_count(slides[i]) for i in idxs)

    toc_layout = None
    best = 1                                        # need >=2 repeated fields for a TOC
    for lid in decor_by_layout:
        if _score(lid) > best:
            best, toc_layout = _score(lid), lid
    for lid, idxs in decor_by_layout.items():
        role = "toc" if lid == toc_layout else "section"
        buckets.setdefault(role, []).extend(idxs)

    # Positional fallback for templates that carry NO role signal at all --
    # every slide sits on the plain "Blank" layout with the design baked onto
    # the slide (a common shape for machine-generated or heavily flattened
    # decks). Neither the layout name nor the body-slot / repeat-field signals
    # distinguish the pages, so we fall back to the one universal convention:
    # the deck opens on a cover and closes on a thank-you. We only *lift* a
    # slide the name/structural passes parked in the generic content bucket,
    # so a real divider or TOC is never stolen, and never on a one-slide deck.
    content_bucket = buckets.get("content", [])

    def _lift(idx: int, role: str, aliases=()) -> None:
        if any(idx in buckets.get(r, []) for r in (role,) + tuple(aliases)):
            return
        if idx not in content_bucket:
            return
        buckets.setdefault(role, []).append(idx)
        buckets["content"] = [i for i in buckets["content"] if i != idx]

    # Only fire when the name and structural passes found NO role at all (the
    # sole bucket is generic content) -- a deck that already names a cover or
    # divider is never second-guessed by position.
    if len(slides) > 2 and set(buckets) <= {"content", "section", "toc"}:
        _lift(0, "cover")
        _lift(len(slides) - 1, "close", aliases=("closing",))

    # A title-layout slide that sits at the tail of the deck is a thank-you /
    # closing page, not another cover -- the deck opens on its cover and closes
    # on the same layout. Only split when the template gave no explicit closing
    # role and the cover pool has more than one slide; we keep the earliest as
    # the cover and park the rest as closings. Literal-free (position + count).
    cover_idx = buckets.get("cover", [])
    if (len(cover_idx) >= 2 and not buckets.get("closing")
            and not buckets.get("close")):
        # Only the covers that sit *after* every other role are tail closers
        # (the deck reuses the title layout to say thank-you). Covers grouped
        # at the head -- alternate first slides a designer left in the template
        # -- stay in the cover pool. Literal-free: pure position + count.
        last_other = -1
        for role, idxs in buckets.items():
            if role == "cover":
                continue
            for i in idxs:
                last_other = max(last_other, i)
        closers = [i for i in cover_idx if i > last_other]
        if closers and len(closers) < len(cover_idx):
            buckets["cover"] = [i for i in cover_idx if i <= last_other]
            buckets["close"] = closers

    return {r: sorted(v) for r, v in buckets.items() if v}


# ---------------------------------------------------------------------------
# shape helpers (shared vocabulary for callers)
# ---------------------------------------------------------------------------

def _is_body_placeholder(shape) -> bool:
    try:
        return (shape.is_placeholder
                and shape.placeholder_format.idx in (0, 1, 2, 3, 4))
    except (AttributeError, ValueError):
        return False


def clear_body(slide, keep: Iterable[int] = ()) -> int:
    """Delete every non-placeholder shape; optionally keep some placeholders.

    ``keep`` lists placeholder idx values to preserve (default: title only).
    Returns the number of shapes removed.
    """
    removed = 0
    for sh in list(slide.shapes):
        if sh.is_placeholder:
            try:
                idx = int(sh.placeholder_format.idx)
            except (AttributeError, ValueError):
                idx = -1
            if idx in keep:
                continue
        sh._element.getparent().remove(sh._element)
        removed += 1
    return removed


def layout_placeholder_text(slide, idx: int = 0) -> str:
    """Text of the *layout* placeholder with ``idx`` on ``slide``'s layout.

    This is what an empty slide placeholder resolves back to. Most renderers
    (LibreOffice, WPS, the Tencent Docs preview) fall back to the layout when a
    slide placeholder body carries no run of its own, so a template layout
    whose title placeholder still holds its skeleton text
    (``单击此处编辑母版标题样式``) will have that string painted in the layout's
    slot on every slide that keeps an empty placeholder.
    """
    try:
        layout = slide.slide_layout
    except Exception:
        return ""
    for sh in layout.shapes:
        if not getattr(sh, "is_placeholder", False):
            continue
        try:
            if int(sh.placeholder_format.idx) != idx:
                continue
        except (AttributeError, ValueError):
            continue
        try:
            return sh.text_frame.text or ""
        except Exception:
            return ""
    return ""


def drop_empty_placeholders(slide, idx: Iterable[int] | None = None) -> int:
    """Remove placeholders that carry no text. Returns how many were dropped.

    An empty placeholder is *not* inert -- it is dead template DNA. Because it
    resolves back to its layout twin, leaving one behind paints the layout's
    prompt text (``单击此处编辑母版标题样式``) in the layout's slot; in an
    editor it also shows a "click to add title" box. Any page whose header is
    hand-built must call this, which is why the reference deck's pages carry
    no placeholders at all.

    ``idx`` restricts the sweep to specific placeholder indices.
    """
    removed = 0
    for sh in list(slide.shapes):
        if not getattr(sh, "is_placeholder", False):
            continue
        try:
            this_idx = int(sh.placeholder_format.idx)
        except (AttributeError, ValueError):
            this_idx = -1
        if idx is not None and this_idx not in idx:
            continue
        try:
            text = (sh.text_frame.text or "").strip()
        except Exception:
            text = ""
        if text:
            continue
        sh._element.getparent().remove(sh._element)
        removed += 1
    return removed


def set_title(slide, text: str, *, reposition: tuple | None = None) -> bool:
    """Write into the title placeholder (idx 0), preserving the placeholder's
    own paragraph formatting (alignment/spacing inherited from the layout).
    Unlike ``TextFrame.clear()`` this keeps lvl1pPr of paragraph 0 intact.

    ``reposition=(top_in, height_in)`` moves the title placeholder below the
    content chrome bar (Kimi-style) instead of leaving it at the template's
    default top slot -- the default slot overlaps the blue bar, which was a
    recurring visual bug. Resets margins and centers vertically.
    """
    for sh in slide.shapes:
        if sh.is_placeholder and sh.placeholder_format.idx == 0:
            tf = sh.text_frame
            # drop extra paragraphs, keep the first with its pPr
            paras = list(tf.paragraphs)
            for p in paras[1:]:
                p._p.getparent().remove(p._p)
            p = tf.paragraphs[0]
            for r in list(p.runs):
                r._r.getparent().remove(r._r)
            run = p.add_run()
            run.text = text
            if reposition:
                top_in, height_in = reposition
                mx = 0.9
                sh.left = Inches(mx); sh.top = Inches(top_in)
                sh.width = Inches(13.333 - 2 * mx); sh.height = Inches(height_in)
                tf.vertical_anchor = MSO_ANCHOR.MIDDLE
                tf.margin_top = tf.margin_bottom = 0
            return True
    return False


# ---------------------------------------------------------------------------
# reusable chrome / cover primitives (Kimi-quality, DNA-driven)
# ---------------------------------------------------------------------------

#: 专病 deck content-page chrome signature (brand blue + light dots)
CHROME_BAR = "1185FE"
CHROME_DOT1 = "C8ECFF"
CHROME_DOT2 = "70B6FE"


def box(slide, x, y, w, h, hex_color: str, shape=MSO_SHAPE.RECTANGLE):
    """Add a solid-fill, shadow-less shape (internal drawing primitive)."""
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb = RGBColor.from_string(hex_color)
    s.line.fill.background()
    s.shadow.inherit = False
    return s


def set_geom(shape, prst: str, adj: dict | None = None) -> None:
    """Rewrite a shape's preset geometry to ``prst`` (e.g. ``'cloud'``,
    ``'homePlate'``, ``'round2DiagRect'``, ``'round2SameRect'``).

    python-pptx's ``MSO_SHAPE`` enum lacks some presets (FREEFORM /
    HOME_PLATE / round2SameRect), so we patch the raw ``prstGeom`` directly.

    ``adj`` supplies adjustment values in the raw 1/100000 encoding, e.g.
    ``{"adj1": 5681, "adj2": 0}`` -- presets like ``round2SameRect`` (corners
    rounded on ONE side only, as used by the 专病 chapter bar) are nothing like
    the default ``roundRect`` without them.
    """
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    sp = shape._element.spPr
    g = sp.find(f"{{{A}}}prstGeom")
    if g is None:
        from lxml import etree
        g = etree.SubElement(sp, f"{{{A}}}prstGeom")
    g.set("prst", prst)
    av = g.find(f"{{{A}}}avLst")
    if av is None:
        from lxml import etree
        av = etree.SubElement(g, f"{{{A}}}avLst")
    if adj is not None:
        from lxml import etree
        for child in list(av):
            av.remove(child)
        for name, val in adj.items():
            gd = etree.SubElement(av, f"{{{A}}}gd")
            gd.set("name", str(name))
            gd.set("fmla", "val %d" % int(val))


# ---------------------------------------------------------------------------
# rotation-aware frame handling
# ---------------------------------------------------------------------------
# The single most expensive bug in this project came from trusting
# ``shape.left/top/width/height``: those are the UNROTATED frame. A shape with
# ``<a:xfrm rot="5400000" flipH="1">`` and ext 3.91x11.01in paints an
# 11.01x3.91in *horizontal* band -- 90 degrees away from what the frame says.
# Every clone that re-drew a template decoration from those numbers silently
# rotated the decoration 90 degrees.

def shape_rot(shape) -> tuple:
    """``(rotation_degrees, flip_h, flip_v)`` from the shape's ``<a:xfrm>``."""
    sp = getattr(shape._element, "spPr", None)
    xfrm = sp.find(qn("a:xfrm")) if sp is not None else None
    if xfrm is None:
        return 0.0, False, False
    return (float(xfrm.get("rot") or 0) / 60000.0,
            xfrm.get("flipH") == "1", xfrm.get("flipV") == "1")


def set_xfrm(shape, x: float, y: float, w: float, h: float, *,
             rot: float = 0.0, flip_h: bool = False, flip_v: bool = False):
    """Write position/size AND rotation/flip into ``<a:xfrm>``.

    python-pptx's ``left/top/width/height`` setters have nowhere to put
    ``rot``/``flipH``/``flipV``, so they get dropped on every redraw. Use this
    whenever you reproduce a decoration that was rotated in the template.
    ``rot`` is in degrees clockwise about the frame centre (as OOXML).
    """
    shape.left, shape.top = Inches(x), Inches(y)
    shape.width, shape.height = Inches(w), Inches(h)
    sp = shape._element.spPr
    xfrm = sp.find(qn("a:xfrm"))
    if xfrm is None:
        from lxml import etree
        xfrm = etree.Element(qn("a:xfrm"))
        sp.insert(0, xfrm)
    if abs(rot) > 0.001:
        xfrm.set("rot", str(int(round((rot % 360) * 60000))))
    else:
        xfrm.attrib.pop("rot", None)
    for attr, on in (("flipH", flip_h), ("flipV", flip_v)):
        if on:
            xfrm.set(attr, "1")
        else:
            xfrm.attrib.pop(attr, None)
    return shape


def _el_bbox(el) -> tuple | None:
    """Rendered ``(L,T,W,H)`` inches of a raw ``p:sp`` / ``p:pic`` element."""
    import math
    sp = el.find(qn("p:spPr"))
    if sp is None:
        sp = el.find(qn("p:grpSpPr"))
    xfrm = sp.find(qn("a:xfrm")) if sp is not None else None
    if xfrm is None:
        return None
    off, ext = xfrm.find(qn("a:off")), xfrm.find(qn("a:ext"))
    if off is None or ext is None:
        return None
    w0 = int(ext.get("cx")) / EMU_PER_INCH
    h0 = int(ext.get("cy")) / EMU_PER_INCH
    cx = int(off.get("x")) / EMU_PER_INCH + w0 / 2
    cy = int(off.get("y")) / EMU_PER_INCH + h0 / 2
    r = (float(xfrm.get("rot") or 0) / 60000.0) % 360
    if abs(r - 90) < 0.01 or abs(r - 270) < 0.01:
        rw, rh = h0, w0
    elif abs(r) < 0.01 or abs(r - 180) < 0.01:
        rw, rh = w0, h0
    else:
        rad = math.radians(r)
        c, s = abs(math.cos(rad)), abs(math.sin(rad))
        rw, rh = w0 * c + h0 * s, w0 * s + h0 * c
    return cx - rw / 2, cy - rh / 2, rw, rh


def rotated_bbox(shape) -> tuple:
    """Rendered ``(left, top, width, height)`` in inches, rotation-aware.

    Use this -- never ``shape.left/top/width/height`` -- for layout maths
    (overlap, overflow, "does this decoration sit behind the title block?").
    """
    bb = _el_bbox(shape._element)
    if bb is not None:
        return bb
    return (shape.left / EMU_PER_INCH, shape.top / EMU_PER_INCH,
            shape.width / EMU_PER_INCH, shape.height / EMU_PER_INCH)


def layout_chrome(slide) -> dict:
    """Inventory of the decoration a slide INHERITS from its layout.

    This is the thing that decides whether the caller may draw chrome at all.
    On the clone route the template layout already paints the content-page
    wash / dots / divider / logos and the section-page rotated chapter bar;
    anything redrawn on top either doubles (logos) or degrades (an opaque bar
    replacing a translucent ``@15% -> @0%`` wash).

    Returns ``{"shapes": [(name, L, T, W, H)], "pictures": int, "bar": bool,
    "divider": bool, "dots": int, "rotated": int, "min_top": float}``.
    """
    lay = slide.slide_layout
    try:
        sw = slide.part.package.presentation_part.presentation.slide_width / EMU_PER_INCH
    except Exception:
        sw = 13.333
    info = {"shapes": [], "pictures": 0, "bar": False, "divider": False,
            "dots": 0, "rotated": 0, "min_top": 99.0}
    for el in lay._element.iter():
        if el.tag not in (qn("p:sp"), qn("p:pic"), qn("p:cxnSp")):
            continue
        if el.find(".//" + qn("p:ph")) is not None:
            continue                    # placeholders never render by themselves
        bb = _el_bbox(el)
        if bb is None:
            continue
        L, T, W, H = bb
        cNvPr = el.find(".//" + qn("p:cNvPr"))
        name = cNvPr.get("name") if cNvPr is not None else "?"
        info["shapes"].append((name, L, T, W, H))
        info["min_top"] = min(info["min_top"], T)
        sp = el.find(qn("p:spPr"))
        xfrm = sp.find(qn("a:xfrm")) if sp is not None else None
        if xfrm is not None and (xfrm.get("rot") or xfrm.get("flipH") or xfrm.get("flipV")):
            info["rotated"] += 1
        if el.tag == qn("p:pic"):
            info["pictures"] += 1
        if W >= 0.85 * sw and T < 0.9 and 0.05 <= H <= 1.4:
            info["bar"] = True
        if W >= 0.85 * sw and 0.4 <= T <= 1.2 and H <= 0.08:
            info["divider"] = True
        g = el.find(".//" + qn("a:prstGeom"))
        if g is not None and g.get("prst") == "ellipse" and W <= 0.9 and T <= 0.9:
            info["dots"] += 1
    return info


def clone_shape(src_shape, dst_slide):
    """Deep-copy a shape's XML into ``dst_slide``, preserving EVERYTHING --
    geometry, ``rot``/``flip``, custom geometry, gradient angle, effects.

    This is how a template decoration should be reused. Re-drawing it from
    ``left/top/width/height`` loses rotation and custom geometry (that is the
    bug class this function exists to kill).

    Only ``<p:sp>`` shapes are supported; pictures need relationship remapping
    -- use :func:`copy_logos` / ``add_picture`` for those (a clear
    ``ValueError`` is raised rather than silently producing a broken rId).
    """
    el = src_shape._element
    if el.tag != qn("p:sp"):
        raise ValueError(
            "clone_shape only handles <p:sp>; got <%s>. Pictures carry r:embed "
            "relationships that must be remapped -- use copy_logos()."
            % el.tag.split("}")[-1])
    new_el = copy.deepcopy(el)
    dst_slide.shapes._spTree.insert_element_before(new_el, "p:extLst")
    return dst_slide.shapes[-1]


def copy_logos(slide, prs=None, layout_name: str = "内容页 - 有标题") -> int:
    """Copy every picture (logo) from the named layout onto ``slide``,
    preserving original geometry. Returns the number copied."""
    import io
    if prs is None:
        return 0
    for master in prs.slide_masters:
        for lay in master.slide_layouts:
            if lay.name == layout_name:
                for sh in lay.shapes:
                    if sh.shape_type == 13 and getattr(sh, "image", None) is not None:
                        slide.shapes.add_picture(io.BytesIO(sh.image.blob),
                                                  sh.left, sh.top, sh.width, sh.height)
                return len([s for s in lay.shapes if s.shape_type == 13])
    return 0


def add_content_chrome(slide, *, prs=None, bar_hex: str = CHROME_BAR,
                       clear: bool = True,
                       layout_name: str = "内容页 - 有标题",
                       width_in: float = 13.333, force: bool = False):
    """Ensure the content page's chrome exists -- WITHOUT drawing it twice.

    THE LESSON THIS ENCODES: on the clone route the template *layout* already
    paints the top wash, the two dots, the hairline and both logos. Redrawing
    them on the slide does not "add" chrome, it *doubles* the logos and
    *degrades* the wash -- the template's bar is ``accent1 @15% -> @0%`` alpha,
    and re-emitted opaque it reads as a hard blue band. So the default here is
    to inherit: if the layout provides the chrome, draw nothing and return 0.

    ``force=True`` reproduces the old behaviour (draw a solid bar + dots +
    divider + logos) for shells whose layout has no chrome at all. When
    forcing, the bar/wash ramp is alpha-ramped to match the template look.

    By default it ``clear_body`` first so the template shell's own decorations
    (stray photos, accent shapes, placeholder text) never leak through.
    """
    if clear:
        clear_body(slide)
    if not force:
        inv = layout_chrome(slide)
        # Inherit whenever the layout already paints ANY header chrome. A
        # minimal template (logos but no coloured band) is a deliberate design
        # choice -- synthesising a blue bar there injects a foreign accent that
        # violates the template DNA. Only an entirely chrome-less layout needs a
        # synthetic header, which the caller forces for synthetic shells.
        if inv["bar"] or inv["pictures"]:
            return 0                       # layout already owns the header look
    box(slide, 0, 0, width_in, 0.71, bar_hex)
    for (lx, ly, sz) in [(-0.20, 0.10, 0.46), (0.10, 0.31, 0.27)]:
        d = box(slide, lx, ly, sz, sz, CHROME_DOT1, MSO_SHAPE.OVAL)
        gradient_fill(d, [(0, CHROME_DOT1, 30), (100, bar_hex, 100)])
    box(slide, 0, 0.71, width_in, 0.012, bar_hex)
    copy_logos(slide, prs=prs, layout_name=layout_name)
    return 4


def _strip_md(text):
    """Strip inline markdown emphasis so raw ** markers never reach a slide."""
    import re as _re
    if not isinstance(text, str) or not text:
        return text
    prev = None
    while prev != text:
        prev = text
        text = _re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = _re.sub(r"\*\*", "", text)
        text = _re.sub(r"(?<![\w])\*(?![\s])(.+?)(?<![\s])\*(?![\w])", r"\1", text)
        text = _re.sub(r"(?<![\w])\*(?![\s])(.+)", r"\1", text)
        text = _re.sub(r"(.+)\*(?![\w])", r"\1", text)
        text = text.replace("`", "")
    return text


def _inplace_text(slide, old_markers, new_text, *, multi=False):
    """Replace the contents of the template shell's OWN text box that matches
    any marker substring, preserving geometry, font, colour, size, alignment
    and bold. Returns True when a box was rewritten.

    Clone-route contract for cover/closing: edit the template's text, never
    wipe-and-redraw. Redrawing synthesises chrome (pills, bands, centred
    titles, photos) the template cover may not even have, which is exactly the
    fidelity regression these two pages kept hitting.
    """
    if not new_text:
        return False
    for sh in slide.shapes:
        if not (sh.has_text_frame and sh.text_frame.text.strip()):
            continue
        if any(m and m in sh.text_frame.text for m in old_markers):
            tf = sh.text_frame
            lines = new_text.splitlines() if multi else [new_text]
            p0 = tf.paragraphs[0]
            if p0.runs:
                p0.runs[0].text = lines[0]
                for r in p0.runs[1:]:
                    r.text = ""
            else:
                r = p0.add_run(); r.text = lines[0]
            first_src = tf.paragraphs[0].runs[0] if tf.paragraphs[0].runs else None
            for extra in lines[1:]:
                np = tf.add_paragraph()
                nr = np.add_run(); nr.text = extra
                if first_src is not None:
                    nr.font.size = first_src.font.size
                    nr.font.bold = first_src.font.bold
                    nr.font.name = first_src.font.name
                    try:
                        nr.font.color.rgb = first_src.font.color.rgb
                    except Exception:
                        pass
            return True
    return False


def _iter_text_shapes(slide):
    for sh in slide.shapes:
        try:
            if sh.has_text_frame and sh.text_frame.text.strip():
                yield sh
        except Exception:
            continue


def _font_size_pt(sh):
    """Largest run font size (pt) in a text shape; 0 when undefined."""
    best = 0.0
    try:
        for para in sh.text_frame.paragraphs:
            for run in para.runs:
                if run.font.size:
                    best = max(best, run.font.size.pt)
    except Exception:
        return 0.0
    return best


def _shape_style(sh):
    """Capture the dominant run style (size/bold/name/colour) of a shape so it
    can be re-applied after the box is cleared. ``None`` fields fall back to the
    box's own defaults, which keeps the inherited template DNA."""
    model = None
    for para in sh.text_frame.paragraphs:
        if para.runs:
            model = para.runs[0]; break
    style = {"size": None, "bold": None, "name": None, "color": None}
    if model is not None:
        style["size"] = model.font.size
        style["bold"] = model.font.bold
        style["name"] = model.font.name
        try:
            style["color"] = model.font.color.rgb
        except Exception:
            style["color"] = None
    return style


def _write_box(sh, text, *, multi=False, align=None):
    """Replace a text shape's contents with ``text`` while preserving its
    geometry, font, colour, size and alignment (the inherited DNA). All of the
    template's own sample paragraphs/runs are removed first so none of them
    leaks through; the original run style is re-applied to every written line."""
    style = _shape_style(sh)
    tf = sh.text_frame
    # capture the model run's full property block (a:rPr) before clearing, so
    # the rewritten text inherits the template DNA byte-for-byte -- theme
    # colours (scheme LIGHT_1 etc.), typefaces and weights that a per-field
    # rgb copy silently drops, which made white cover titles render dark gray.
    model_rPr = None
    for para in tf.paragraphs:
        for run in para.runs:
            rPr = run._r.find(qn("a:rPr"))
            if rPr is not None:
                model_rPr = copy.deepcopy(rPr)
                break
        if model_rPr is not None:
            break
    # remove every paragraph but the first
    first_p = tf.paragraphs[0]._p
    parent = first_p.getparent()
    for para in list(tf.paragraphs)[1:]:
        parent.remove(para._p)
    # remove every run of the first paragraph
    a_r = "{http://schemas.openxmlformats.org/drawingml/2006/main}r"
    for r in list(first_p.findall(a_r)):
        first_p.remove(r)
    lines = text.splitlines() if multi else [text]
    lines = [ln for ln in lines] or [text]

    def emit(paragraph, content):
        run = paragraph.add_run()
        run.text = content
        if model_rPr is not None:
            # rPr must be the first child of <a:r>, before the <a:t> element.
            run._r.insert(0, copy.deepcopy(model_rPr))
            return
        if style["size"] is not None:
            run.font.size = style["size"]
        if style["bold"] is not None:
            run.font.bold = style["bold"]
        if style["name"] is not None:
            run.font.name = style["name"]
        if style["color"] is not None:
            try:
                run.font.color.rgb = style["color"]
            except Exception:
                pass

    emit(tf.paragraphs[0], lines[0])
    for extra in lines[1:]:
        emit(tf.add_paragraph(), extra)
    if align is not None:
        for para in tf.paragraphs:
            para.alignment = align


def _empty_ph_shapes(slide):
    """Empty placeholder boxes on ``slide`` in authoring order (title idx 0
    first). These are writable targets that carry the template's inherited
    heading style but start blank -- the common case for a cover whose title
    box the author left empty. Text shapes that already have content are not
    returned (those are handled by the size rank)."""
    out = []
    for sh in slide.shapes:
        try:
            if (sh.is_placeholder and sh.has_text_frame
                    and not sh.text_frame.text.strip()):
                out.append(sh)
        except Exception:
            continue
    out.sort(key=lambda s: int(s.placeholder_format.idx))
    return out


def _rank_text_shapes(slide, *, include_empty_ph=False):
    """Return text shapes sorted by descending font size -- the largest is the
    page title, the rest supporting lines. Role-based, no literal matching.

    With ``include_empty_ph`` the blank placeholders (a cover's empty title /
    subtitle slots) are appended in authoring order so callers can still write
    into a shell whose sample text the author left empty.
    """
    shapes = list(_iter_text_shapes(slide))
    shapes.sort(key=_font_size_pt, reverse=True)
    if include_empty_ph:
        have = {id(s) for s in shapes}
        shapes.extend(s for s in _empty_ph_shapes(slide) if id(s) not in have)
    return shapes


def _cluster_by_size(slide) -> list[tuple[int, list]]:
    """Group non-empty text shapes by (rounded) font size.

    Returns ``[(size_pt, [shapes ...]), ...]`` ordered by descending size; the
    shapes inside a cluster are sorted in reading order (top, then left) so a
    horizontally-spread TOC and a vertically-stacked one both come out in the
    author's intended sequence. A cluster with more than one member is a
    *repeated field* -- the structural signature of a table-of-contents grid.
    """
    groups: dict[int, list] = {}
    for sh in _iter_text_shapes(slide):
        pt = _font_size_pt(sh)
        if not pt:
            continue
        groups.setdefault(int(round(pt)), []).append(sh)

    def reading_order(sh):
        top = (sh.top or 0) / EMU_PER_INCH
        left = (sh.left or 0) / EMU_PER_INCH
        return (round(top, 1), left)

    return [(size, sorted(shs, key=reading_order))
            for size, shs in sorted(groups.items(), key=lambda kv: -kv[0])]


def _blank_box(sh):
    """Empty a text shape in place, keeping it (and its formatting) for reuse."""
    tf = sh.text_frame
    first_p = tf.paragraphs[0]._p
    a_r = "{http://schemas.openxmlformats.org/drawingml/2006/main}r"
    for para in list(tf.paragraphs)[1:]:
        para._p.getparent().remove(para._p)
    for r in list(first_p.findall(a_r)):
        first_p.remove(r)


def slide_foreground(slide):
    """The template's own text colour for ``slide``, as a hex string or None.

    Reads the *largest* run on the shell -- the page title, the element whose
    colour the author chose against that page's background -- and returns its
    inherited RGB. Used by the synthetic fallbacks so a hand-drawn divider or
    TOC keeps the template's contrast (black ink on a white layout, white on a
    dark one) instead of a fixed palette. No literal colours are matched; the
    value simply comes from the DNA already present on the shell.
    """
    ranked = _rank_text_shapes(slide)
    for sh in ranked:
        color = _shape_style(sh).get("color")
        if color is not None:
            try:
                return str(color)
            except Exception:
                continue
    return None


def rebuild_section(slide, *, prs=None, title_text="", meta_text="",
                    chapter_num=""):
    """Rebuild a section/divider page by editing the template shell's OWN text.

    Same fidelity contract as :func:`rebuild_cover` -- edit in place, inherit
    colour/font/geometry/background, never wipe-and-redraw. The shell's boxes
    are ranked by font size:

      * the biggest box is the display element (a chapter number in most
        templates) -> ``chapter_num`` when given, else ``title_text``;
      * the next box takes ``title_text`` when the biggest box was the number;
      * a following box takes ``meta_text`` (byline/date).

    Everything the template painted (the rotated band, both logos, the master
    background, and the inherited run colour -- black on a light divider, white
    on a dark one) survives untouched. This is what kills the white-on-white
    section bug: the divider text simply keeps whatever colour the template's
    own heading box already used.
    """
    title_text = _strip_md(title_text)
    meta_text = _strip_md(meta_text)
    chapter_num = _strip_md(chapter_num)
    ranked = _rank_text_shapes(slide)
    if not ranked:
        return False
    want = title_text or chapter_num or meta_text
    if not want:
        return False
    # A *display* box is the one whose font dwarfs the rest -- the oversized
    # numeral ("01") a divider paints for a chapter index. It is a structural
    # signal (>=1.7x the next size), never a literal match, and it is sized for
    # a token, not a heading: overflowing a title into it wrecks the layout.
    # When the caller has a number it belongs there; when it does not, the box
    # is blanked so no stale sample leaks and the title drops to the heading box.
    display = 0 if len(ranked) > 1 and \
        _font_size_pt(ranked[0]) >= 1.7 * max(_font_size_pt(ranked[1]), 1) else -1
    if display == 0:
        # a real display-numeral box exists
        if chapter_num:
            _write_box(ranked[0], chapter_num)
        else:
            _blank_box(ranked[0])
        body, slots = ranked[1:], [title_text, meta_text]
    else:
        # no oversized box -- the biggest box is the heading itself
        body, slots = ranked, [title_text or chapter_num, meta_text]
    si = 0
    for sh in body:
        while si < len(slots) and not slots[si]:
            si += 1
        if si >= len(slots):
            break
        _write_box(sh, slots[si])
        si += 1
    return True


def rebuild_toc(slide, *, prs=None, items=None, title_text="", title_en=""):
    """Rebuild a table-of-contents page in place from the shell's own grid.

    A TOC is recognised structurally, not by any label: it is the hand-composed
    page that repeats a *field* -- several equal-font boxes in reading order. We
    fill the title cluster with the chapter names and, when a second repeated
    cluster of larger display numerals exists, the index cluster with ``01``,
    ``02`` ... Slots left past the item count are blanked (never carry stale
    template text). All colour, font, size and geometry -- the inherited DNA --
    are kept exactly as the template authored them, so the deck stays black-on-
    white on a white template and white-on-dark on a dark one.
    """
    items = [it for it in (items or []) if it]
    clusters = _cluster_by_size(slide)
    # repeated-field clusters (>=2 boxes) are the TOC grid, biggest display first
    repeated = [(sz, shs) for sz, shs in clusters if len(shs) >= 2]
    # the smaller-font repeated cluster holds the chapter titles; a larger-font
    # repeated cluster (if any) is the index numerals.
    titles_slot = None
    nums_slot = None
    if repeated:
        titles_slot = repeated[-1][1]                 # smallest font = titles
        others = repeated[:-1]
        if others:
            nums_slot = others[0][1]                  # next-larger = numerals
    elif clusters:
        # only a single group (e.g. one merged title row) -> fill titles there
        titles_slot = clusters[0][1]

    applied = False
    if titles_slot and items:
        for k, sh in enumerate(titles_slot):
            if k < len(items):
                it = items[k]
                name = (it.get("title") if isinstance(it, dict) else it[0]) \
                    if it else ""
                _write_box(sh, _strip_md(str(name)))
                applied = True
            else:
                _blank_box(sh)
    if nums_slot and applied:
        for k, sh in enumerate(nums_slot):
            _write_box(sh, "%02d" % (k + 1))
    # a leading single-box cluster may carry the page heading (CONTENTS / 目录);
    # leave it as the template authored it unless a caller supplies text and it
    # is clearly the unique (non-repeated) heading box.
    return applied


def rebuild_cover(slide, *, prs=None, pill_text="", title_text="",
                  meta_text="", bar_hex=CHROME_BAR, font="思源黑体"):
    """Rebuild a cover by editing the template shell's OWN text IN PLACE.

    Field identity is by font-size rank, not literals: the biggest text box
    becomes the title, the next one becomes the byline/meta. Everything else --
    logos, colours, positions, sizes, the layout's background -- is inherited
    byte-for-byte, which is the whole point of the clone route. We never wipe
    the shell or synthesise a photo/pill/wash band, because a template cover
    may legitimately have none of those.
    """
    title_text = _strip_md(title_text)
    meta_text = _strip_md(meta_text)
    pill_text = _strip_md(pill_text)
    ranked = _rank_text_shapes(slide, include_empty_ph=True)
    if title_text and ranked:
        _write_box(ranked[0], title_text, multi=True)
    byline = meta_text or pill_text
    if byline:
        target = ranked[1] if len(ranked) > 1 else (ranked[0] if ranked else None)
        if target is not None and target is not (ranked[0] if title_text else None):
            _write_box(target, byline)
    # any placeholder we did not write would resolve back to its layout twin and
    # paint the master's "click to edit" prompt -- drop those dead DNA slots.
    drop_empty_placeholders(slide)
    return


def rebuild_closing(slide, *, prs=None, title_text="", sub_text="",
                    meta_text="", font="思源黑体",
                    title_size=36, sub_size=18, meta_size=13,
                    title_color="0D64BF", sub_color="0D64BF",
                    meta_color="68737F"):
    """Rebuild a closing page by editing the template shell's own text IN PLACE.

    Closing reuses the cover shell, so it follows the identical fidelity
    contract: swap the biggest-font box for the closing title and the next box
    for the byline/subtitle, inheriting all other design DNA. No photo, no band,
    no invented chrome.
    """
    title_text = _strip_md(title_text)
    sub_text = _strip_md(sub_text)
    meta_text = _strip_md(meta_text)
    ranked = _rank_text_shapes(slide, include_empty_ph=True)
    if not ranked:
        return False
    from pptx.enum.text import PP_ALIGN as _A
    slots = [x for x in (title_text, sub_text, meta_text) if x]
    if not slots:
        return False
    # fill one line per available box in rank order; if the shell offers fewer
    # boxes than lines, stack the remainder inside the last box. Closing keeps
    # the route's centered convention (the cover heading is authored centred).
    extra = []
    if len(slots) > len(ranked):
        extra = slots[len(ranked) - 1:]
        slots = slots[:len(ranked) - 1]
    for i, line in enumerate(slots):
        _write_box(ranked[i], line, align=_A.CENTER)
    if extra and ranked:
        # any surplus lines go to the SMALLEST box (the byline slot) -- never
        # the oversized display title, which would stack several giant lines and
        # collide. Its inherited small-font style keeps them as a compact footer.
        foot = ranked[-1]
        # replace (never prepend) the shell's own sample byline -- the closing
        # owns these lines now; keeping them leaked "汇报人：XXX" from the cover.
        _write_box(foot, "\n".join(extra), multi=True, align=_A.CENTER)
    drop_empty_placeholders(slide)
    return True


def _cover_text(slide, x, y, w, h, anchor, text, size, color, *, bold=False,
                font: str = "思源雅黑", align=None):
    """Single-run text box helper for chrome/cover builders."""
    tf = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf.text_frame.word_wrap = True
    tf.text_frame.vertical_anchor = anchor
    tf.text_frame.margin_left = tf.text_frame.margin_right = 0
    tf.text_frame.margin_top = tf.text_frame.margin_bottom = 0
    p = tf.text_frame.paragraphs[0]
    if align is not None:
        p.alignment = align
    r = p.add_run(); r.text = text
    r.font.size = Pt(size); r.font.bold = bold
    r.font.name = font
    r.font.color.rgb = RGBColor.from_string(color)
    return tf


# ---------------------------------------------------------------------------
# the deck
# ---------------------------------------------------------------------------

class ShellExhausted(RuntimeError):
    """Raised when no unused shell of the requested role remains."""


class CloneShell:
    """Owns a writable copy of a template and hands out page shells."""

    def __init__(self, template: str,
                 role_map: Sequence[tuple[str, str]] = DEFAULT_ROLES):
        self.src = os.path.abspath(template)
        fd, self.work = tempfile.mkstemp(suffix=".pptx", prefix="clonedeck_")
        os.close(fd)
        shutil.copyfile(self.src, self.work)
        self.prs = Presentation(self.work)
        self.n: int = len(self.prs.slides._sldIdLst)
        self.buckets = classify_shells(self.prs, role_map)
        self._cursors = {role: 0 for role in self.buckets}
        self.used: set[int] = set()
        self._assigned: list[tuple[int, str]] = []  # (idx, role)

    # -- inspection ---------------------------------------------------------
    def counts(self) -> dict[str, int]:
        return {r: len(v) for r, v in self.buckets.items()}

    def slide(self, idx: int):
        return self.prs.slides[idx]

    # -- allocation ---------------------------------------------------------
    def take(self, role: str, cleared: bool = True):
        """Grab the next unused shell of ``role``; clear its body if asked."""
        pool = self.buckets.get(role) or []
        cur = self._cursors.get(role, 0)
        while cur < len(pool) and pool[cur] in self.used:
            cur += 1
        if cur >= len(pool):
            raise ShellExhausted(f"no unused '{role}' shell left "
                                 f"(have {len(pool)})")
        self._cursors[role] = cur + 1
        idx = pool[cur]
        self.used.add(idx)
        self._assigned.append((idx, role))
        sl = self.prs.slides[idx]
        if cleared:
            clear_body(sl)
        return idx, sl


    def _duplicate_for_role(self, role: str, *, cleared: bool = True):
        """Duplicate the last used shell of this role when the pool is exhausted."""
        import copy
        from lxml import etree
        pool = self.buckets.get(role) or []
        candidates = [idx for idx in pool if idx in self.used]
        if not candidates:
            candidates = list(self.used)
        if not candidates:
            candidates = [0]
        src_idx = candidates[-1]
        src_slide = self.prs.slides[src_idx]
        # deep-copy the slide XML and append it
        slide_count = len(self.prs.slides._sldIdLst)
        self.prs.slides.add_slide(src_slide.slide_layout)
        new_idx = len(self.prs.slides._sldIdLst) - 1
        new_slide = self.prs.slides[new_idx]
        # copy shapes from source
        for shape in list(new_slide.shapes):
            shape._element.getparent().remove(shape._element)
        for shape in src_slide.shapes:
            el = copy.deepcopy(shape._element)
            new_slide.shapes._spTree.append(el)
        if cleared:
            clear_body(new_slide)
        self.used.add(new_idx)
        self.buckets.setdefault(role, []).append(new_idx)
        self._assigned.append((new_idx, role))
        return new_idx, new_slide

    def assign(self, idx: int, role: str = "custom", cleared: bool = True):
        """Pin a specific template slide (e.g. the real cover with its photo)."""
        if idx in self.used:
            raise ValueError(f"shell {idx} already assigned")
        self.used.add(idx)
        self._assigned.append((idx, role))
        sl = self.prs.slides[idx]
        if cleared:
            clear_body(sl)
        return sl

    def plan_capacity(self, need: dict[str, int]) -> tuple[bool, list[str]]:
        """Check the template can serve a ``{role: count}`` demand."""
        problems = []
        for role, n in need.items():
            if self.counts().get(role, 0) < n:
                problems.append(f"{role}: need {n}, have {self.counts().get(role, 0)}")
        return (not problems), problems

    # -- finalisation -------------------------------------------------------
    def finish(self, out_path: str, order: Sequence[int] | None = None) -> str:
        """Prune unused slides, reorder kept ones, save to ``out_path``.

        ``order`` = original template indices in final sequence. Defaults to
        assignment order.
        """
        order = list(order) if order is not None else [i for i, _ in self._assigned]
        keep = set(order)
        xml_slides = self.prs.slides._sldIdLst
        snap = list(xml_slides)
        for i in range(self.n):
            if i not in keep:
                try:
                    self.prs.part.drop_rel(snap[i].get(qn('r:id')))
                except KeyError:
                    pass
                xml_slides.remove(snap[i])
        for i in order:
            el = snap[i]
            xml_slides.remove(el)
            xml_slides.append(el)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        self.prs.save(out_path)
        return out_path

    def close(self):
        try:
            os.remove(self.work)
        except OSError:
            pass

    # -- context manager ----------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---------------------------------------------------------------------------
# page audit (visual-QA loop: the step that actually caught the framework
# overflow in the 专病数据库 deck -- generate -> audit -> fix -> re-audit)
# ---------------------------------------------------------------------------

def _dw(s: str) -> float:
    return sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in (s or ""))


def _wrap_h(text: str, width_in: float, size_pt: float, mul: float = 1.30) -> float:
    unit = size_pt / 72.0
    cpl = max(4.0, width_in / unit * 0.98)
    lines = max(1, int(_dw(text) / cpl + 0.999))
    return lines * unit * mul


def audit_pages(prs, overflow_tol_in: float = 0.06,
                collide_tol_in: float = 0.08) -> list:
    """Heuristic per-page layout audit (python-pptx cannot measure real text
    layout, so we estimate CJK-aware wrapped height per text frame).

    Returns a list of ``{"page", "kind", "msg"}`` dicts. Empty list = clean.

    Kinds:
    - ``overflow``   estimated wrapped text taller than its box
    - ``collision``  two non-empty text boxes overlapping materially
    - ``empty``      a slide with zero non-empty text frames
    - ``doubling``   a slide shape drawn on top of the layout's own decoration
                     (logos / bar / divider) -- on the clone route every layout
                     decoration renders already, so redrawing it double-prints
    - ``stale_placeholder``  an empty placeholder left on the slide whose layout
                     twin still carries text. Renderers resolve an empty
                     placeholder back to the layout, so the layout's skeleton
                     string (``单击此处编辑母版标题样式``) gets painted. Drop it
                     with ``drop_empty_placeholders`` -- this is the "DNA not
                     cleaned up" class.
    """
    issues = []
    for pi, slide in enumerate(prs.slides, 1):
        lay_chrome = layout_chrome(slide)
        for sh in slide.shapes:
            if not getattr(sh, "is_placeholder", False):
                continue
            try:
                ph_idx = int(sh.placeholder_format.idx)
                ph_text = (sh.text_frame.text or "").strip()
            except (AttributeError, ValueError):
                continue
            if ph_text:
                continue
            prompt = layout_placeholder_text(slide, ph_idx).strip()
            if not prompt:
                continue
            issues.append({
                "page": pi, "kind": "stale_placeholder",
                "msg": f'empty placeholder idx={ph_idx} on slide; the layout '
                       f'twin renders "{prompt[:24]}" in its slot '
                       f'(use drop_empty_placeholders)'})
        for sh in slide.shapes:
            try:
                sL, sT, sW, sH = rotated_bbox(sh)
            except (TypeError, ZeroDivisionError):
                continue
            for (nm, lL, lT, lW, lH) in lay_chrome["shapes"]:
                if (sW >= 0.3 and abs(sL - lL) < 0.12 and abs(sT - lT) < 0.12
                        and abs(sW - lW) < 0.25 and abs(sH - lH) < 0.25):
                    issues.append({
                        "page": pi, "kind": "doubling",
                        "msg": f'slide shape at ({sL:.2f},{sT:.2f}) {sW:.2f}x{sH:.2f} '
                               f'doubles layout decoration "{nm}"'})
                    break
        boxes = []
        for sh in slide.shapes:
            try:
                # rotation-aware: a 90deg-rotated bar's real footprint is the
                # transposed frame, not left/top/width/height
                L, T, Wd, Ht = rotated_bbox(sh)
            except (TypeError, ZeroDivisionError):
                continue
            if not getattr(sh, "has_text_frame", False):
                continue
            tf = sh.text_frame
            text = tf.text.strip()
            if not text:
                continue
            eh = 0.0
            for p in tf.paragraphs:
                ptxt = "".join(r.text for r in p.runs)
                if not ptxt:
                    continue
                sz = max((r.font.size.pt for r in p.runs if r.font.size), default=12)
                uw = max(0.4, Wd - (tf.margin_left + tf.margin_right) / EMU_PER_INCH)
                eh += _wrap_h(ptxt, uw, sz)
            eh += (tf.margin_top + tf.margin_bottom) / EMU_PER_INCH
            if eh > Ht + overflow_tol_in:
                issues.append({"page": pi, "kind": "overflow",
                               "msg": f'"{text[:18]}..." est {eh:.2f}in > box {Ht:.2f}in'})
            boxes.append((L, T, Wd, Ht, text[:14]))
        for a in range(len(boxes)):
            for b in range(a + 1, len(boxes)):
                x1, y1, w1, h1, t1 = boxes[a]
                x2, y2, w2, h2, t2 = boxes[b]
                ox = min(x1 + w1, x2 + w2) - max(x1, x2)
                oy = min(y1 + h1, y2 + h2) - max(y1, y2)
                if ox > collide_tol_in and oy > collide_tol_in and _dw(t1) > 2 and _dw(t2) > 2:
                    issues.append({"page": pi, "kind": "collision",
                                   "msg": f'"{t1}" x "{t2}" ov {ox:.2f}x{oy:.2f}in'})
        if not boxes:
            issues.append({"page": pi, "kind": "empty", "msg": "no text-bearing shapes"})
        # Duplicate text in different shapes on one page. Two distinct
        # situations look identical to a naive count:
        #   (a) a real bug — the same string drawn twice (a chip label also
        #       painted beside it). This shows up as EXACTLY 2 occurrences.
        #   (b) a card/tile template — N cards sharing the same short field
        #       label ("关注核心" / "业务特征与难点"). This is by design and
        #       shows up as >= 3 occurrences of a *short* string.
        # So: flag any long string (>= 12 CJK-equivalent cols) repeated at
        # least twice, plus any short string repeated exactly twice.
        seen = {}
        for _, _, _, _, t in boxes:
            key = t.strip()
            if _dw(key) >= 6:
                seen[key] = seen.get(key, 0) + 1
        for key, cnt in seen.items():
            w = _dw(key)
            if cnt > 1 and (w >= 12 or cnt == 2):
                issues.append({"page": pi, "kind": "duplicate",
                               "msg": f'"{key}..." appears {cnt}x on one page'})
    return issues


# ---------------------------------------------------------------------------
# gradients (the visual "premium" lever: light->brand blue ramps, etc.)
# ---------------------------------------------------------------------------

def gradient_fill(shape, stops, angle: float = 0.0, *,
                  rot_with_shape: bool | None = None):
    """Apply a linear gradient to ``shape``.

    ``stops`` accepts either plain hex strings (evenly spaced, opaque), or
    tuples ``(pos_0_100, "RRGGBB")`` / ``(pos_0_100, "RRGGBB", alpha_pct)``.
    ``alpha_pct`` is OPACITY in percent (0 = fully transparent, 100 = opaque)
    -- the 专病 template's header "bar" is really ``1185FE @15% -> @0%``, a
    translucent wash fading to nothing, so alpha is not optional decoration
    here: drawing it opaque turns a soft haze into a hard blue band.

    ``angle`` in degrees, 0 = left-to-right. Uses python-pptx's
    FillFormat.gradient(), then rewrites the gsLst so 3+ stops work (the stock
    API only exposes the default 2-stop ramp).

    ``rot_with_shape`` writes the ``rotWithShape`` attribute; pass ``True``
    when the shape itself is rotated and the ramp must rotate with it.
    """
    from pptx.dml.color import RGBColor
    norm = []
    if stops and isinstance(stops[0], (list, tuple)):
        for s in stops:
            norm.append((float(s[0]), s[1], float(s[2]) if len(s) > 2 else 100.0))
    else:
        n = len(stops)
        norm = [(0.0 if n == 1 else i * 100.0 / (n - 1), c, 100.0)
                for i, c in enumerate(stops)]
    norm = sorted(norm)
    f = shape.fill
    try:
        f.gradient()
    except Exception:
        pass
    # rebuild gsLst via raw XML for arbitrary stop counts
    spPr = shape._element.spPr
    from pptx.oxml.ns import qn
    grad = spPr.find(qn('a:gradFill'))
    if grad is None:
        raise ValueError("gradient() did not create gradFill")
    for old in list(grad):
        grad.remove(old)
    from lxml import etree
    A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    gsLst = etree.SubElement(grad, f'{{{A}}}gsLst')
    for pos, hexc, alpha in norm:
        gsel = etree.SubElement(gsLst, f'{{{A}}}gs')
        gsel.set('pos', str(int(round(pos * 1000))))
        clr = etree.SubElement(gsel, f'{{{A}}}srgbClr')
        clr.set('val', str(hexc).upper().lstrip('#'))
        if alpha < 100.0:
            a = etree.SubElement(clr, f'{{{A}}}alpha')
            a.set('val', str(int(round(max(0.0, alpha) * 1000))))
    lin = etree.SubElement(grad, f'{{{A}}}lin')
    lin.set('ang', str(int(round((angle % 360) * 60000))))
    lin.set('scaled', '1')
    if rot_with_shape is not None:
        grad.set('rotWithShape', '1' if rot_with_shape else '0')
    return shape


