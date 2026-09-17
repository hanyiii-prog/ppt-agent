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
           "rebuild_closing",
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


def classify_shells(prs: Presentation,
                    role_map: Sequence[tuple[str, str]] = DEFAULT_ROLES
                    ) -> dict[str, list[int]]:
    """Bucket slide indices by role using their layout name."""
    buckets: dict[str, list[int]] = {}
    for i, slide in enumerate(prs.slides):
        name = slide.slide_layout.name or ""
        role = "content"
        for key, r in role_map:
            if key in name:
                role = r
                break
        buckets.setdefault(role, []).append(i)
    return buckets


# ---------------------------------------------------------------------------
# shape helpers (shared vocabulary for callers)
# ---------------------------------------------------------------------------

def _is_body_placeholder(shape) -> bool:
    try:
        return (shape.is_placeholder
                and shape.placeholder_format.idx in (0, 1, 2, 3, 4))
    except (AttributeError, ValueError):
        return False


def clear_body(slide, keep: Iterable[int] = (0,)) -> int:
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
        if inv["bar"] and inv["pictures"]:
            return 0                       # layout already paints the chrome
    box(slide, 0, 0, width_in, 0.71, bar_hex)
    for (lx, ly, sz) in [(-0.20, 0.10, 0.46), (0.10, 0.31, 0.27)]:
        d = box(slide, lx, ly, sz, sz, CHROME_DOT1, MSO_SHAPE.OVAL)
        gradient_fill(d, [(0, CHROME_DOT1, 30), (100, bar_hex, 100)])
    box(slide, 0, 0.71, width_in, 0.012, bar_hex)
    copy_logos(slide, prs=prs, layout_name=layout_name)
    return 4


def rebuild_cover(slide, *, prs=None, pill_text: str = "天津市口腔医院",
                  title_text: str = "", meta_text: str = "",
                  bar_hex: str = CHROME_BAR, font: str = "思源雅黑") -> None:
    """Rebuild a cover with correct z-order by cloning the template's own
    chrome, then injecting title/meta on top:

        background photo -> 2 blue freeform bands -> 2 logos -> pill
        (rounded-rect, white label) -> 44pt title -> bottom meta

    Fixes the V6 bug where the LOGO was drawn last (on top of the title) and
    "天津市口腔医院" was wrongly merged into the 44pt title. The pill is a
    separate ``round2DiagRect`` element so it never collides with the title.
    """
    import io
    bg_blob = None
    bands = []
    for sh in list(slide.shapes):
        if sh.shape_type == 13 and sh.top is not None and sh.top / EMU_PER_INCH < 0:
            bg_blob = sh.image.blob
        if "FREEFORM" in str(sh.shape_type):
            bands.append(copy.deepcopy(sh._element))
    for sh in list(slide.shapes):
        sh._element.getparent().remove(sh._element)
    if bg_blob:
        slide.shapes.add_picture(io.BytesIO(bg_blob), 0, Inches(-0.07),
                                  Inches(13.333), Inches(4.72))
    for bx in bands:
        slide.shapes._spTree.append(bx)
    copy_logos(slide, prs=prs)
    pill = box(slide, 4.38, 4.81, 4.87, 0.61, bar_hex, MSO_SHAPE.ROUNDED_RECTANGLE)
    try:
        pill.adjustments[0] = 0.10
    except Exception:
        pass
    gradient_fill(pill, [(0, "0C67BC"), (100, "1687F1")])
    set_geom(pill, "round2DiagRect")
    _cover_text(slide, 4.67, 4.91, 4.29, 0.40, MSO_ANCHOR.MIDDLE,
                pill_text, 24, "FFFFFF", bold=True, font=font)
    if title_text:
        _cover_text(slide, 1.11, 5.58, 11.41, 0.89, MSO_ANCHOR.MIDDLE,
                    title_text, 44, "0D64BF", bold=True, font=font)
    if meta_text:
        _cover_text(slide, 2.50, 6.56, 8.64, 0.36, MSO_ANCHOR.MIDDLE,
                    meta_text, 16, "0D64BF", font=font, align=PP_ALIGN.CENTER)


def rebuild_closing(slide, *, prs=None, title_text: str = "", sub_text: str = "",
                    meta_text: str = "", font: str = "思源雅黑",
                    title_size: int = 36, sub_size: int = 18,
                    meta_size: int = 13, title_color: str = "0D64BF",
                    sub_color: str = "0D64BF", meta_color: str = "68737F") -> None:
    """Rebuild a closing page by **reusing the shell's own media**, never by
    redrawing it.

    Closing pages almost always reuse the cover shell, so the page already
    carries a background photo plus the two translucent blue "wave" bands
    (``0061FA @75% -> @0`` freeforms washing down from the top). The template's
    look is: photo + waves over the top ~4.7in, logo pair, three centred text
    blocks, and **white below** -- there is no full-page background.

    The V9 closing cleared the body and then drew a full-page opaque gradient
    plus an opaque rounded rect: the photo disappeared, the waves lost their
    alpha, and the page rendered solid blue. This primitive captures the photo
    blob and the freeform bands first, re-appends them in draw order, then
    writes the closing texts (centred, matching the reference).
    """
    import io
    bg_blob = None
    bands = []
    for sh in list(slide.shapes):
        if (sh.shape_type == 13 and sh.top is not None
                and sh.top / EMU_PER_INCH < 0):
            bg_blob = sh.image.blob
        elif "FREEFORM" in str(sh.shape_type):
            bands.append(copy.deepcopy(sh._element))
    for sh in list(slide.shapes):
        sh._element.getparent().remove(sh._element)
    if bg_blob:
        slide.shapes.add_picture(io.BytesIO(bg_blob), 0, Inches(-0.07),
                                  Inches(13.333), Inches(4.72))
    for bx in bands:
        slide.shapes._spTree.append(bx)
    copy_logos(slide, prs=prs)
    if title_text:
        _cover_text(slide, 1.11, 5.17, 11.11, 0.78, MSO_ANCHOR.MIDDLE,
                    title_text, title_size, title_color, bold=True, font=font,
                    align=PP_ALIGN.CENTER)
    if sub_text:
        _cover_text(slide, 1.11, 6.11, 11.11, 0.42, MSO_ANCHOR.MIDDLE,
                    sub_text, sub_size, sub_color, font=font,
                    align=PP_ALIGN.CENTER)
    if meta_text:
        _cover_text(slide, 1.11, 6.69, 11.11, 0.33, MSO_ANCHOR.MIDDLE,
                    meta_text, meta_size, meta_color, font=font,
                    align=PP_ALIGN.CENTER)


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
        if not any(_dw(t) > 2 for _, _, _, _, t in boxes):
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
