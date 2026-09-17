# -*- coding: utf-8 -*-
"""page_kits -- reusable page-composition kits for the clone-shell route.

Learned from the Kimi v1 -> v2 revision of the 专病数据库 deck (2026-09). Each
kit draws a full content page body on top of the shared content chrome
(bar + 2 dots + divider + logos) and takes plain data, so a planner can emit a
page without hand-placing every shape.

Why these exist
---------------
The v1 deck used dense tables and thin text rows for org / responsibility /
timeline pages; the reviewer asked for "一眼看懂" (readable at a glance)
and a graphic timeline. v2 replaced them with:

- four bordered **role cards** instead of a RACI table
- a real **org-chart** page (top node -> connector bus -> 2 groups -> dept cards)
- **two-panel icon lists** (data-safety / interface "two-step")
- a dated **progress narrative** with 3-state status chips (done/doing/plan)
- an arrow **stage timeline** with an orange "current stage" banner

Kits
----
- ``content_header(slide, title, lead)``            chrome + title + lead
- ``four_role_cards(slide, cards, note)``           4 responsibility cards
- ``org_chart(slide, top, groups, depts, note)``    org structure diagram
- ``two_panel_list(slide, left, right)``            two bordered panels, icon rows
- ``progress_timeline(slide, steps, note)``         dated rows, 3-state chips
- ``stage_timeline(slide, stages, current, note)``  homePlate arrows + banner

Palette follows the 专病 deck. Typography defaults to 思源雅黑.
"""
from __future__ import annotations

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from .clone_shell import (CHROME_BAR, add_content_chrome, box, clear_body,
                          gradient_fill, layout_chrome, set_geom)

# --- palette ---------------------------------------------------------------
P = CHROME_BAR            # brand blue bar
PD = "09437F"             # title / heading navy
INK = "0D64BF"            # inline blue
PS = "F4F9FF"             # light panel
CHIP = "EAF4FF"           # light chip fill
DIV = "BFD9F5"            # hairline / connector
TXT = "262626"            # body text
MUT = "68737F"            # muted text
WHITE = "FFFFFF"

GRAD_PRIMARY = ("0C67BC", "1687F1")
GRAD_STAGE2 = ("2B8FF0", "5EB0F8")
GRAD_STAGE3 = ("70B6FE", "9CCBFB")
GRAD_WARN = ("F5A623", "FFBA55")      # "current / in progress" orange
GRAD_PLAN = ("A9CFFB", "BDD9FA")      # not-yet-started light blue

#: status -> gradient ramp for dated/progress chips
STATUS = {"done": GRAD_PRIMARY, "doing": GRAD_WARN, "plan": GRAD_PLAN}

FONT = "思源雅黑"

# --- vertical grid ---------------------------------------------------------
# Values are the template's / Kimi's own, not invented ones:
#   * the content layout's title placeholder sits at (0.438, 0.097) -- i.e. the
#     title belongs ON the header wash. The wash is `accent1 @15% -> @0%`
#     alpha, so a dark navy title on it is high-contrast; moving the title
#     *below* the bar (an earlier "contrast fix") was fixing a bar that was
#     only opaque because we had redrawn it wrong.
#   * Kimi's content page: hd-title (0.539, 0.147) 20B, sub (0.556, 0.861)
#     14B, first card at y=1.389.
M = 0.556                 # side margin
TITLE_X, TITLE_Y = 0.539, 0.147
TITLE_W, TITLE_H = 9.306, 0.436
LEAD_X, LEAD_Y = 0.556, 0.861
LEAD_W, LEAD_H = 12.222, 0.333
TOP = 1.389               # content top
BOT = 7.05                # content bottom
NOTE_H = 0.83
NOTE_Y = BOT - NOTE_H

# --- chapter (section) page grid, straight from the template/Kimi ----------
CH_TITLE = (1.564, 2.100, 8.889, 1.212)      # 44pt bold, white
CH_LINE = (1.586, 3.450, 6.596, 0.019)       # white hairline
CH_LIST = (1.562, 3.728, 6.521, 1.376)       # 14pt bold, white, N lines


# --- primitives ------------------------------------------------------------
def _tb(slide, x, y, w, h, lines, *, size=11, color=TXT, bold=False,
        font=FONT, align=None, anchor=MSO_ANCHOR.TOP, spacing=None):
    """Add a text box.

    ``lines`` is a str (optionally with ``\\n``) or a list of entries; each
    entry is either ``(text, size, color, bold)`` / a plain string (= one
    paragraph), or a **list of such tuples** (= ONE paragraph with several
    styled runs, e.g. "3 " blue-bold + task text + muted owner).
    """
    shp = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = shp.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    if isinstance(lines, str):
        lines = [(ln, size, color, bold) for ln in lines.split("\n")]
    for i, ln in enumerate(lines):
        if isinstance(ln, (list, tuple)) and ln and isinstance(ln[0], (list, tuple)):
            runs = list(ln)                       # multi-run paragraph
        elif isinstance(ln, (list, tuple)):
            runs = [ln]
        else:
            runs = [(ln, size, color, bold)]
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if align is not None:
            p.alignment = align
        if spacing is not None:
            p.line_spacing = spacing
        for rspec in runs:
            t, sz, c, b = rspec
            r = p.add_run()
            r.text = t
            r.font.size = Pt(sz)
            r.font.bold = b
            r.font.name = font
            r.font.color.rgb = RGBColor.from_string(c)
    return shp


def _round(slide, x, y, w, h, *, fill=None, grad=None, line=None, lw=1.0,
           radius=0.10, prst="roundRect"):
    """Add a (optionally rounded / re-geometried) rectangle."""
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                 Inches(x), Inches(y), Inches(w), Inches(h))
    if prst != "roundRect":
        set_geom(shp, prst)
    if grad:
        gradient_fill(shp, [(0, grad[0]), (100, grad[1])])
        shp.line.fill.background()
    elif fill:
        shp.fill.solid()
        shp.fill.fore_color.rgb = RGBColor.from_string(fill)
        if line:
            shp.line.color.rgb = RGBColor.from_string(line)
            shp.line.width = Pt(lw)
        else:
            shp.line.fill.background()
    shp.shadow.inherit = False
    if prst == "roundRect":
        try:
            shp.adjustments[0] = radius
        except Exception:
            pass
    return shp


def _hair(slide, x, y, w, h=0.012, color=DIV):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                               Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb = RGBColor.from_string(color)
    s.line.fill.background(); s.shadow.inherit = False
    return s


def _icon(slide, x, y, size, color=P, shape="cloud"):
    s = slide.shapes.add_shape(MSO_SHAPE.OVAL,
                               Inches(x), Inches(y), Inches(size), Inches(size))
    try:
        set_geom(s, shape)
    except Exception:
        pass
    s.fill.solid(); s.fill.fore_color.rgb = RGBColor.from_string(color)
    s.line.fill.background(); s.shadow.inherit = False
    return s


# --- kit: header -----------------------------------------------------------
def content_header(slide, title, lead=None, *, prs=None, title_size=20,
                   lead_size=14):
    """Ensure the content chrome + write the title and optional lead.

    Two things this does NOT do, deliberately:

    * it does not draw the header wash / dots / divider / logos -- the template
      layout already paints them, and redrawing doubled the logos and replaced
      the translucent ``#1185FE @15% -> @0%`` wash with an opaque band. It only
      asks :func:`add_content_chrome`, which inherits when it can.
    * it does not push the title *below* the wash. The title belongs on it
      (template placeholder ``0.438, 0.097``; Kimi ``0.539, 0.147``).

    The title is written *into* the kept title placeholder (repositioned),
    not a side text box -- otherwise ``clear_body`` leaves the template's own
    title text in PH0 and it shows through as a stale/duplicate heading.
    """
    add_content_chrome(slide, prs=prs)          # inherits when the layout has it
    wrote = False
    for sh in slide.shapes:
        if sh.is_placeholder and sh.placeholder_format.idx == 0:
            sh.left, sh.top = Inches(TITLE_X), Inches(TITLE_Y)
            sh.width, sh.height = Inches(TITLE_W), Inches(TITLE_H)
            tf = sh.text_frame
            tf.word_wrap = True
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf.margin_left = tf.margin_right = 0
            tf.margin_top = tf.margin_bottom = 0
            paras = list(tf.paragraphs)
            for p in paras[1:]:
                p._p.getparent().remove(p._p)
            p0 = tf.paragraphs[0]
            for r in list(p0.runs):
                r._r.getparent().remove(r._r)
            r = p0.add_run()
            r.text = title
            r.font.size = Pt(title_size)
            r.font.bold = True
            r.font.name = FONT
            r.font.color.rgb = RGBColor.from_string(PD)
            wrote = True
            break
    if not wrote:
        _tb(slide, TITLE_X, TITLE_Y, TITLE_W, TITLE_H, title, size=title_size,
            color=PD, bold=True)
    if lead:
        _tb(slide, LEAD_X, LEAD_Y, LEAD_W, LEAD_H, lead, size=lead_size,
            color=INK, bold=True)
    return TOP


# --- kit: chapter / section page -------------------------------------------
def chapter_page(slide, title, lines, *, prs=None, title_size=44):
    """A chapter divider page -- and the canonical example of *inheriting*
    template chrome instead of redrawing it.

    The template's ``章节标题页`` layout already contains the whole design:

        * a white background (master ``bgRef idx="1001" -> bg1``)
        * one rounded bar, ``prst=round2SameRect``, ``adj1=5681 adj2=0``,
          ``xfrm rot=5400000 flipH="1"``, ``ext 3.911x11.007in`` -- which
          renders as an 11.007x3.911in HORIZONTAL band at (0.00, 1.63)
          because of that 90-degree rotation
        * both logos

    So this kit clears the slide and draws ONLY text. Earlier versions drew a
    full-bleed blue rectangle (hiding the white background), re-drew the band
    from ``left/top/width/height`` -- losing ``rot``, so it came out vertical
    -- and copied the logos again on top of the layout's. Three bugs, one
    cause: redrawing chrome the layout already renders.

    ``lines`` is the sub-topic list, one entry per line (white, bold, 14pt).
    """
    clear_body(slide, keep=())        # drop the shell's own decorations + PH
    if isinstance(lines, str):
        lines = [ln for ln in lines.split("\n") if ln.strip()]
    x, y, w, h = CH_TITLE
    _tb(slide, x, y, w, h, title, size=title_size, color=WHITE, bold=True,
        anchor=MSO_ANCHOR.MIDDLE)
    lx, ly, lw, lh = CH_LINE
    _hair(slide, lx, ly, lw, lh, WHITE)
    if lines:
        cx, cy, cw, ch = CH_LIST
        _tb(slide, cx, cy, cw, ch,
            [(ln, 14, WHITE, True) for ln in lines], spacing=1.45)
    return slide


# --- kit: table of contents --------------------------------------------------
# Geometry is the reference deck's own, captured shape-by-shape from its TOC
# page -- not invented:
#   deco-circle  (9.7222,4.4444) 4.4444sq  ellipse, 1185FE @7.843% -> @1.961%
#                                            at 45deg  (barely visible by design)
#   toc-title    (0.8333,1.6667) 3.0556x0.8333  44pt bold PD
#   toc-title-en (0.8611,2.5833) 3.0556x0.3056  15pt bold #A3E0FF
#   toc-accent   (0.8611,3.0833) 0.7778x0.0694  roundRect adj=50000
#   toc-note     (0.8611,3.4722) 3.1944x1.6667  11pt MUT
#   item<k>      number column x=4.5833, y = 1.5000 + k*1.2500
#                num circle 0.7500sq, 70B6FE->1185FE at 45deg
#                title +1.0278,+0.0000  6.6667x0.4167  20pt bold PD
#                sub   +1.0278,+0.4444  6.6667x0.2778  10.5pt MUT
#                rule  +0.0000,+1.0000  7.9167x0.0097
TOC_DECO = (9.7222, 4.4444, 4.4444, 4.4444)
TOC_TITLE = (0.8333, 1.6667, 3.0556, 0.8333)
TOC_TITLE_EN = (0.8611, 2.5833, 3.0556, 0.3056)
TOC_ACCENT = (0.8611, 3.0833, 0.7778, 0.0694)
TOC_NOTE = (0.8611, 3.4722, 3.1944, 1.6667)
TOC_ITEM_X = 4.5833
TOC_ITEM_Y0 = 1.5000
TOC_ITEM_PITCH = 1.2500
TOC_ITEM_SUB = "68737F"
TOC_TITLE_EN_COLOR = "A3E0FF"


def toc_page(slide, items, note=None, *, title="目录", title_en="CONTENTS",
             prs=None):
    """A table-of-contents page in the reference deck's layout.

    ``items`` is a list of ``(title, sub)`` pairs (or dicts with ``title`` /
    ``sub``); the ordinal ``01``, ``02``, ... is generated. Four fit at the
    reference pitch; extras are ignored.

    The template ships no dedicated TOC layout -- the reference authors built
    this page on the *content* shell, so the header wash / dots / divider /
    logos are inherited from it (``add_content_chrome`` finds them and returns
    0 -- nothing is redrawn).

    The one thing that must NOT be inherited is the shell's title placeholder,
    and it leaks in *two* ways:

    * **blank slot** -- an empty placeholder resolves back to its layout twin,
      so renderers that fall back to the layout (LibreOffice / WPS / the
      Tencent Docs preview) paint the layout's skeleton heading
      ``单击此处编辑母版标题样式`` across the top of the page;
    * **stale filled slot** -- the template's own contents shell ships a title
      placeholder already holding its heading (here: ``项目实施路径``), which
      survives ``clear_body`` because that keeps the title slot.

    Both are cured by the same move: this header is hand-built, so the shell
    must give up the slot entirely rather than blank it. Hence
    ``clear_body(slide, keep=())`` before the chrome call. (If a caller does
    keep a placeholder and then writes its own header, the narrower
    :func:`~ppt_agent.clone_shell.drop_empty_placeholders` is the tool, and
    ``audit_pages`` reports the leftover as ``stale_placeholder``.)
    """
    clear_body(slide, keep=())              # the page owns its header
    add_content_chrome(slide, prs=prs)      # inherits; draws nothing here

    dx, dy, dw, dh = TOC_DECO
    deco = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(dx), Inches(dy),
                                  Inches(dw), Inches(dh))
    gradient_fill(deco, [(0, P, 7.843), (100, P, 1.961)], 45,
                  rot_with_shape=True)
    deco.line.fill.background()
    deco.shadow.inherit = False

    x, y, w, h = TOC_TITLE
    _tb(slide, x, y, w, h, title, size=44, color=PD, bold=True,
        anchor=MSO_ANCHOR.MIDDLE)
    x, y, w, h = TOC_TITLE_EN
    _tb(slide, x, y, w, h, title_en, size=15, color=TOC_TITLE_EN_COLOR,
        bold=True)
    x, y, w, h = TOC_ACCENT
    _round(slide, x, y, w, h, fill=P, radius=0.50)
    if note:
        x, y, w, h = TOC_NOTE
        if isinstance(note, str):
            note = [ln for ln in note.split("\n") if ln.strip()]
        _tb(slide, x, y, w, h, [(ln, 11, MUT, False) for ln in note],
            spacing=1.45)

    for k, item in enumerate(items[:4]):
        if isinstance(item, dict):
            it_title = item.get("title", "")
            it_sub = item.get("sub", "")
        else:
            pair = list(item) + ["", ""]
            it_title, it_sub = pair[0], pair[1]
        iy = TOC_ITEM_Y0 + k * TOC_ITEM_PITCH
        circ = slide.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(TOC_ITEM_X), Inches(iy),
            Inches(0.750), Inches(0.750))
        gradient_fill(circ, [(0, GRAD_STAGE3[0]), (100, P)], 45,
                      rot_with_shape=True)
        circ.line.fill.background()
        circ.shadow.inherit = False
        _tb(slide, TOC_ITEM_X, iy, 0.750, 0.750, "%02d" % (k + 1), size=20,
            color=WHITE, bold=True, align=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE)
        _tb(slide, TOC_ITEM_X + 1.0278, iy, 6.6667, 0.4167, it_title, size=20,
            color=PD, bold=True)
        if it_sub:
            _tb(slide, TOC_ITEM_X + 1.0278, iy + 0.4444, 6.6667, 0.2778,
                it_sub, size=10.5, color=TOC_ITEM_SUB)
        _hair(slide, TOC_ITEM_X, iy + 1.0000, 7.9167, 0.0097, DIV)
    return slide


# --- kit: quad cards (2x2 icon cards -- Kimi's 建设背景 page) ---------------
# Geometry copied from the reference page, not invented:
#   c1 (0.556,1.389) 5.972x2.639   c2 (6.806,1.389)   c3 (0.556,4.250)
#   icon-bg 0.556sq at +0.277,+0.250   title at +1.000,+0.250 (4.722x0.556)
#   body 5.417x1.528 at +0.277,+0.944
QUAD_GAP = 0.278
QUAD_CARD = (5.972, 2.639)
QUAD_PITCH_Y = 2.861


def quad_cards(slide, cards, note=None, *, title="", lead=None, prs=None,
               top=None):
    """Four icon cards in a 2x2 grid, then an optional note bar.

    ``cards`` = list of 1..4 ``{"title", "body", "icon"}`` where ``body`` is
    either a string or a list of ``(text, kind)`` runs with
    ``kind`` in ``("", "b", "i")`` -- plain / **bold** / *bold inline-blue*.
    That run model exists to reproduce the reference page's emphasis (it bolds
    the diagnosis and prints key conclusions in #0D64BF).
    """
    top = content_header(slide, title, lead, prs=prs) if top is None else top
    cw, chh = QUAD_CARD
    if note:
        # The reference grid and the note bar cannot both take full height:
        # rows land at top and top+QUAD_PITCH_Y, so with a note present the
        # card height compresses until the second row clears the bar
        # (NOTE_Y - 0.30). Without a note the cards keep the exact
        # reference geometry (QUAD_CARD 5.972x2.639).
        chh = NOTE_Y - 0.30 - top - QUAD_PITCH_Y
    for i, c in enumerate(cards[:4]):
        x = M + (i % 2) * (cw + QUAD_GAP)
        y = top + (i // 2) * QUAD_PITCH_Y
        _round(slide, x, y, cw, chh, fill=WHITE, line=DIV, lw=1.0, radius=0.055)
        _round(slide, x + 0.277, y + 0.250, 0.556, 0.556,
               grad=GRAD_STAGE3, radius=0.50)
        _icon(slide, x + 0.416, y + 0.389, 0.278, P, c.get("icon", "cloud"))
        _tb(slide, x + 1.000, y + 0.250, cw - 1.222, 0.556, c["title"],
            size=15, color=PD, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        body = c.get("body", "")
        _tb(slide, x + 0.277, y + 0.944, cw - 0.554, chh - 1.05,
            _runs(body), spacing=1.35)
    if note:
        _note_bar(slide, note)


def _runs(body, size=10.5, color=TXT):
    """Normalise a body into ``_tb`` lines: str -> plain; list -> styled runs
    merged into one paragraph per group. ``color`` is the plain-run colour
    (pass a light colour when the body sits on a dark gradient panel)."""
    if isinstance(body, str):
        return [(body, size, color, False)]
    out = []
    for item in body:
        if isinstance(item, str):
            out.append((item, size, color, False))
            continue
        txt = item[0]
        kind = item[1] if len(item) > 1 else ""
        if kind == "b":
            out.append((txt, size, color, True))
        elif kind == "i":
            out.append((txt, size, INK, True))
        else:
            out.append((txt, size, color, False))
    return out


# --- kit: N-column cards with head band + bottom panel ---------------------
# One parametric kit reproduces five different reference pages, because they
# are all the same grid at different sizes:
#   三大试点  cols=3 w=3.97 h=5.56 head=0.72   top=1.33
#   四大功能  cols=4 w=2.94 h=4.42 head=0.89   top=1.33  + 12.22x1.11 bar@5.94
#   四方协同  cols=4 w=2.94 h=4.58 head=1.19   top=1.39  + 12.22x0.83 bar@6.22
#   三步任务  cols=3 w=3.97 h=1.50 head=0      top=1.33
#   三项承诺  cols=3 w=3.97 h=3.33 head=0      top=1.39  + 12.22x2.00 bar@5.06


#: column-count -> inter-card gap. Taken from the reference pages so the
#: resulting x-positions land on the same pixels (3 cols -> 0.556/4.681/8.806,
#: 4 cols -> 0.556/3.667/6.778/9.889).
_COL_GAP = {3: 0.153, 4: 0.171}


def column_cards(slide, cards, *, cols=None, title="", lead=None, prs=None,
                 top=None, bottom=None, head_h=0.0, card_h=None, gap=None,
                 ramps=None, bottom_grad=False, bottom_icon=None,
                 head_size=13, sub_size=10):
    """N equal columns; each card optionally gets a gradient head band (title +
    sub) and body lines or chips. ``bottom`` adds a full-width panel.

    ``cards``  = ``{"title","sub","lines":[str],"chips":[str],"grad":bool,
                    "icon":str}`` -- an ``icon`` switches the card to the
                   *centred* layout (big icon, then title under it), which is
                   the "三项承诺" style.
    ``bottom`` = ``{"title","body","chips":[str],"h":float,"y":float,
                    "grad":bool,"icon":str}``

    ``top``/``gap`` default to the shared grid; pass them to match a reference
    exactly.
    """
    n = cols or len(cards)
    # always run the header (it clears the shell and writes the title); ``top``
    # only overrides where the *body grid* starts, for reference-exact pages.
    hdr_top = content_header(slide, title, lead, prs=prs)
    top = hdr_top if top is None else top
    ramps = ramps or [GRAD_PRIMARY, GRAD_STAGE2, GRAD_STAGE3]
    if gap is None:
        gap = _COL_GAP.get(n, 0.15)
    w = (13.333 - 2 * M - gap * (n - 1)) / n
    if bottom:
        bh = bottom.get("h", 1.11)
        by = BOT - bh if bottom.get("y") is None else bottom["y"]
    else:
        bh = 0.0
        by = BOT
    card_h = card_h or (by - top - (0.29 if bottom else 0.0))
    for i, c in enumerate(cards[:n]):
        x = M + i * (w + gap)
        _round(slide, x, top, w, card_h, fill=WHITE, line=DIV, lw=1.0, radius=0.055)
        if c.get("icon"):
            # centred icon block: icon -> title -> body
            _round(slide, x + w / 2 - 0.4165, top + 0.305, 0.833, 0.833,
                   grad=GRAD_STAGE3, radius=0.50)
            _icon(slide, x + w / 2 - 0.2085, top + 0.514, 0.417, P, c["icon"])
            _tb(slide, x + 0.222, top + 1.305, w - 0.444, 0.361, c["title"],
                size=15, color=PD, bold=True, align=PP_ALIGN.CENTER)
            _tb(slide, x + 0.277, top + 1.750, w - 0.554, card_h - 1.85,
                _runs(c.get("body", ""), size=c.get("size", 10.0)), spacing=1.30)
            continue
        ry = top
        if head_h:
            if c.get("grad"):
                _round(slide, x, top, w, head_h, grad=ramps[i % len(ramps)],
                       radius=0.055)
                tcol, scol = WHITE, WHITE
            else:
                _round(slide, x, top, w, head_h, fill=CHIP, line=DIV, radius=0.055)
                tcol, scol = PD, INK
            _tb(slide, x + 0.16, top + 0.06, w - 0.32, head_h - 0.12,
                [(c["title"], head_size, tcol, True)] +
                ([(c.get("sub", ""), sub_size, scol, False)] if c.get("sub") else []),
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
            ry = top + head_h + 0.18
        else:
            _tb(slide, x + 0.17, top + 0.16, w - 0.34, 0.40, c["title"], size=13,
                color=PD, bold=True, align=PP_ALIGN.CENTER)
            ry = top + 0.66
        for chip in c.get("chips", []) or []:
            _round(slide, x + 0.22, ry, w - 0.44, 0.40, fill=CHIP, radius=0.30)
            _tb(slide, x + 0.22, ry, w - 0.44, 0.40, chip, size=10.5, color=INK,
                bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
            ry += 0.50
        lines = c.get("lines", [])
        if isinstance(lines, str):
            lines = [lines]
        if lines:
            norm = [ln if isinstance(ln, (list, tuple)) and not isinstance(ln, str)
                    else (ln, c.get("size", 10), TXT, False) for ln in lines]
            _tb(slide, x + 0.20, ry, w - 0.40, top + card_h - ry - 0.16,
                norm, spacing=1.32)
    if bottom:
        bgrad = bottom.get("grad", bottom_grad)
        _round(slide, M, by, 13.333 - 2 * M, bh,
               grad=GRAD_PRIMARY if bgrad else None,
               fill=None if bgrad else PS,
               line=None if bgrad else DIV, radius=0.06)
        tx = M + 0.30
        if bottom.get("icon"):
            _round(slide, M + 0.416, by + 0.555, 0.611, 0.611,
                   grad=GRAD_STAGE3, radius=0.50)
            _icon(slide, M + 0.60, by + 0.74, 0.245, P, bottom["icon"])
            tx = M + 1.388
        tcol = WHITE if bgrad else PD
        bcol = "EAF4FF" if bgrad else TXT
        _tb(slide, tx, by + (0.305 if bottom.get("icon") else 0.12),
            13.333 - tx - 0.30, 0.389, bottom["title"], size=17 if bgrad else 13,
            color=tcol, bold=True)
        if bottom.get("body"):
            _tb(slide, tx, by + (0.777 if bottom.get("icon") else 0.50),
                13.333 - tx - 0.30, bh - (0.9 if bottom.get("icon") else 0.62),
                _runs(bottom["body"], size=11.5 if bgrad else 10.5,
                      color=bcol),
                spacing=1.32)
        cx, cy = M + 0.30, by + 0.52
        for chip in bottom.get("chips", []) or []:
            _round(slide, cx, cy, 1.39, 0.47, fill=CHIP, radius=0.22)
            _tb(slide, cx, cy, 1.39, 0.47, chip, size=10, color=INK, bold=True,
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
            cx += 1.61
    return top


# --- kit: homePlate stage cards + task list (推进安排) ----------------------
STAGE_RAMPS = (("0C67BC", "1687F1"), ("2B8FF0", "5EB0F8"), ("70B6FE", "9CCBFB"))


def stage_cards(slide, stages, tasks=None, *, task_title=None, title="",
                lead=None, prs=None, top=None, card_h=1.50):
    """Three ``homePlate`` stage cards across the top, then an optional
    two-column numbered task list.

    ``stages`` = ``{"head","desc"}`` -- head 11.5pt bold white, desc 9pt white.
    ``tasks``  = ``{"no","text","owner"}`` or plain ``"text"``; split evenly
    into a left / right column, numbered chip + text + muted owner.
    """
    hdr_top = content_header(slide, title, lead, prs=prs)
    top = hdr_top if top is None else top
    n = len(stages)
    gap = _COL_GAP.get(n, 0.15)
    w = (13.333 - 2 * M - gap * (n - 1)) / n
    for i, st in enumerate(stages):
        x = M + i * (w + gap)
        _round(slide, x, top, w, card_h, grad=STAGE_RAMPS[i % 3],
               prst="homePlate")
        _tb(slide, x + 0.222, top + 0.084, w - 0.778, card_h - 0.167,
            [(st["head"], 11.5, WHITE, True)] +
            ([(st.get("desc", ""), 9.0, WHITE, False)] if st.get("desc") else []),
            spacing=1.30)
    if not tasks:
        return top
    ty = top + card_h + 0.20
    if task_title:
        _tb(slide, M, ty, 6.944, 0.333, task_title, size=14, color=PD, bold=True)
        ty += 0.416
    half = (len(tasks) + 1) // 2
    for col, chunk in enumerate((tasks[:half], tasks[half:])):
        x = M + col * 6.388
        wid = 5.972 if col == 0 else 5.833
        lines = []
        for k, t in enumerate(chunk):
            no = t.get("no") if isinstance(t, dict) else (half * col + k + 1)
            txt = t["text"] if isinstance(t, dict) else t
            own = t.get("owner") if isinstance(t, dict) else None
            row = [("%s " % no, 9.5, P, True), (txt, 9.5, TXT, False)]
            if own:
                row.append(("（%s）" % own, 9.5, MUT, False))
            lines.append(row)
        _tb(slide, x, ty, wid, BOT - ty, lines, spacing=1.24)
    return top


# --- kit: four role cards (replaces a RACI table) --------------------------
def four_role_cards(slide, cards, note=None, *, title="", lead=None, prs=None):
    """Draw N (usually 4) bordered responsibility cards + an optional note bar.

    ``cards`` = list of ``{"name","sub","role","duties":[str,...]}``.
    """
    top = content_header(slide, title, lead, prs=prs)
    n = len(cards)
    gap = 0.13
    w = (13.333 - 2 * M - gap * (n - 1)) / n
    card_bottom = NOTE_Y - 0.25
    card_h = card_bottom - top
    hdr_h = 1.19
    for i, c in enumerate(cards):
        x = M + i * (w + gap)
        _round(slide, x, top, w, card_h, fill=WHITE, line=DIV, lw=1.0, radius=0.08)
        _round(slide, x, top, w, hdr_h, grad=GRAD_PRIMARY, radius=0.08)
        _icon(slide, x + w / 2 - 0.21, top + 0.14, 0.42, WHITE, "cloud")
        _tb(slide, x + 0.10, top + 0.58, w - 0.20, 0.56,
            [(c["name"], 13, WHITE, True), (c.get("sub", ""), 10, "D6E9FF", False)],
            align=PP_ALIGN.CENTER)
        cy = top + 1.36
        _round(slide, x + 0.22, cy, w - 0.44, 0.42, fill=CHIP, radius=0.30)
        _tb(slide, x + 0.22, cy, w - 0.44, 0.42, c["role"], size=12, color=INK,
            bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        duties = [("● " + d, 10, TXT, False) for d in c.get("duties", [])]
        _tb(slide, x + 0.22, cy + 0.58, w - 0.44, card_h - 2.0, duties, spacing=1.35)
    if note:
        _note_bar(slide, note)


def _note_bar(slide, text, *, y=NOTE_Y, h=NOTE_H):
    _round(slide, M, y, 13.333 - 2 * M, h, fill=PS, line=DIV, radius=0.10)
    _icon(slide, M + 0.30, y + 0.22, 0.33, P, "cloud")
    _tb(slide, M + 0.83, y + 0.14, 13.333 - 2 * M - 1.0, h - 0.2, text,
        size=10, color=TXT, bold=True, spacing=1.3)


# --- kit: org chart --------------------------------------------------------
def org_chart(slide, top_node, groups, depts, note=None, *, title="", lead=None,
              prs=None):
    """Draw an org structure: top node pill -> connector bus -> two group
    columns (left chip + right stacked nodes) -> department cards -> note.

    ``top_node`` : str label for the top pill (e.g. "院领导：马文盛")
    ``groups``   : ``{"left": {"label","chip_head","chip_body"},
                     "right":{"label","nodes":[{"head","body","accent":bool}]}}``
    ``depts``    : list of ``{"name","sub","lead","members":[str] or str}``
    """
    top = content_header(slide, title, lead, prs=prs)
    cx = 13.333 / 2
    pill_w = 2.78
    _round(slide, cx - pill_w / 2, top, pill_w, 0.58, grad=GRAD_PRIMARY, radius=0.10)
    _tb(slide, cx - pill_w / 2, top, pill_w, 0.58, top_node, size=14,
        color=WHITE, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    _hair(slide, cx - 0.01, top + 0.58, 0.02, 0.28)
    bus_y = top + 0.86
    lx, rx = 0.83, 8.89            # left / right column x
    lw2, rw2 = 7.50, 3.89          # column widths
    _hair(slide, lx + lw2 / 2, bus_y, 0.02, 0.30)        # left drop
    _hair(slide, rx + rw2 / 2, bus_y, 0.02, 0.30)        # right drop
    _hair(slide, lx + lw2 / 2, bus_y, rx + rw2 / 2 - (lx + lw2 / 2), 0.02)  # bus
    lab_y = bus_y + 0.34
    _tb(slide, lx, lab_y, lw2, 0.25, "▍" + groups["left"]["label"], size=12,
        color=PD, bold=True)
    _tb(slide, rx, lab_y, rw2, 0.25, "▍" + groups["right"]["label"], size=12,
        color=PD, bold=True)
    chip_y = lab_y + 0.33
    lg = groups["left"]
    _round(slide, lx, chip_y, lw2, 0.69, fill=CHIP, line=DIV, radius=0.10)
    _tb(slide, lx + 0.23, chip_y, lw2 - 0.45, 0.69,
        [(lg["chip_head"], 12, PD, True), (lg["chip_body"], 10, INK, False)],
        anchor=MSO_ANCHOR.MIDDLE)
    rnodes = groups["right"]["nodes"]
    ny = chip_y
    for nd in rnodes:
        grad = GRAD_STAGE2 if nd.get("accent") else None
        _round(slide, rx, ny, rw2, 0.69,
               grad=grad, fill=None if grad else CHIP,
               line=None if grad else DIV, radius=0.10)
        _tb(slide, rx + 0.22, ny, rw2 - 0.44, 0.69,
            [(nd["head"], 12, WHITE if grad else PD, True),
             (nd.get("body", ""), 10, WHITE if grad else INK, False)],
            anchor=MSO_ANCHOR.MIDDLE)
        ny += 0.83
    # connectors down to the department row
    dep_y = 3.80
    _hair(slide, lx + lw2 / 2, chip_y + 0.69, 0.02, 0.22)
    dep_bus_y = dep_y - 0.22
    _hair(slide, lx + lw2 / 2, dep_bus_y, 0.02, 0.22)
    # dept cards (3 across the left column width)
    nd = len(depts)
    dgap = 0.15
    dw = (lw2 - dgap * (nd - 1)) / nd
    hub_x = lx + lw2 / 2
    if nd:
        _hair(slide, lx + dw / 2, dep_bus_y, hub_x - (lx + dw / 2), 0.02)
        _hair(slide, hub_x, dep_bus_y, lx + dw * (nd - 1) + dw / 2 - hub_x, 0.02)
    dep_h = 2.60
    for i, d in enumerate(depts):
        x = lx + i * (dw + dgap)
        _hair(slide, x + dw / 2, dep_bus_y, 0.02, 0.14)
        _round(slide, x, dep_y, dw, dep_h, fill=WHITE, line=DIV, radius=0.10)
        _round(slide, x, dep_y, dw, 0.56, grad=GRAD_PRIMARY, radius=0.10)
        _tb(slide, x + 0.11, dep_y, dw - 0.22, 0.56,
            [(d["name"], 12, WHITE, True), (d.get("sub", ""), 9, "D6E9FF", False)],
            align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        mem = d.get("members", [])
        if isinstance(mem, str):
            mem = [mem]
        lines = [("牵头：" + d.get("lead", ""), 10, INK, True)]
        lines += [("成员：" + m, 10, PD, False) for m in mem]
        _tb(slide, x + 0.18, dep_y + 0.68, dw - 0.36, dep_h - 0.8, lines,
            spacing=1.3)
    if note:
        _note_bar(slide, note, y=BOT - 0.47, h=0.47)


# --- kit: two-panel icon list ---------------------------------------------
def two_panel_list(slide, left, right, *, title="", lead=None, prs=None):
    """Two bordered panels; each panel = ``{title, rows:[[head, desc], ...]}``.
    Left rows render with a blue icon + hairline; right rows as light sub-panels.
    """
    top = content_header(slide, title, lead, prs=prs)
    bot = BOT
    pw = 5.97
    gap = 0.28
    ph = bot - top
    for x, panel, sub in ((M, left, False), (M + pw + gap, right, True)):
        _round(slide, x, top, pw, ph, fill=WHITE, line=DIV, radius=0.06)
        _round(slide, x, top, pw, 0.67, grad=GRAD_PRIMARY, radius=0.06)
        _tb(slide, x + 0.27, top, pw - 0.54, 0.67, panel["title"], size=15,
            color=WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        ry = top + 1.05
        rows = panel.get("rows", [])
        if sub:
            for head, desc in rows:
                _round(slide, x + 0.27, ry, pw - 0.54, 1.81, fill=CHIP, radius=0.08)
                _tb(slide, x + 0.52, ry + 0.17, pw - 1.0, 0.33, head, size=13,
                    color=INK, bold=True)
                _tb(slide, x + 0.52, ry + 0.56, pw - 1.0, 1.11, desc, size=10,
                    color=TXT, spacing=1.3)
                ry += 2.00
        else:
            for k, (head, desc) in enumerate(rows):
                if k:
                    _hair(slide, x + 0.36, ry - 0.30, pw - 0.72, 0.012)
                _icon(slide, x + 0.36, ry + 0.10, 0.42, P, "cloud")
                _tb(slide, x + 1.00, ry, pw - 1.3, 0.83,
                    [(head, 11, TXT, True), (desc, 10, TXT, False)], spacing=1.25)
                ry += 1.30


# --- kit: dated progress narrative ----------------------------------------
def progress_timeline(slide, steps, note=None, *, title="", lead=None, prs=None):
    """Vertical narrative: each step = status-colored date chip + title + desc.

    ``steps`` = list of ``{"date","status"(done|doing|plan),"title","desc",
    "current":bool}``. The ``doing`` current row gets a "当前阶段" marker.
    """
    top = content_header(slide, title, lead, prs=prs)
    chip_w, chip_h = 1.78, 0.72
    pitch = 0.86
    tx = 2.72
    tw = 13.333 - tx - M
    n = len(steps)
    for i, s in enumerate(steps):
        y = top + i * pitch
        grad = STATUS.get(s.get("status", "plan"), GRAD_PLAN)
        _round(slide, M, y, chip_w, chip_h, grad=grad, radius=0.08)
        _tb(slide, M, y, chip_w, chip_h, [(s["date"], 12, WHITE, True),
                                          (s.get("status_label", _STATUS_CN[s.get("status", "plan")]), 10, WHITE, False)],
            align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        cur = "　● 当前阶段" if s.get("current") else ""
        _tb(slide, tx, y, tw, 0.31, s["title"] + cur, size=12, color=PD, bold=True)
        _tb(slide, tx, y + 0.31, tw, 0.47, s.get("desc", ""), size=10,
            color=TXT, spacing=1.25)
    if n:
        _hair(slide, M + chip_w / 2, top, 0.02, (n - 1) * pitch + chip_h)
    if note:
        ny = top + n * pitch + 0.20
        _note_bar(slide, note, y=ny, h=BOT - ny)


_STATUS_CN = {"done": "已完成", "doing": "进行中", "plan": "计划"}


# --- kit: stage timeline (arrow stages + current banner) -------------------
def stage_timeline(slide, stages, current=None, note=None, *, title="", lead=None,
                   prs=None):
    """Graphic timeline: orange "current" banner + homePlate stage arrows, each
    with an 上/中/下旬 task column and a milestone badge + a responsibility note.

    ``stages`` = list of ``{"head","tasks":str,"milestone":str,"strong":bool}``
    """
    top = content_header(slide, title, lead, prs=prs)
    if current:
        _round(slide, M, top, 4.58, 0.44, grad=GRAD_WARN, radius=0.10)
        _tb(slide, M + 0.22, top, 4.36, 0.44, "● " + current, size=12,
            color=WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        _icon(slide, 2.08, top + 0.45, 0.36, GRAD_WARN[0], "homePlate")
    # stage row: reference y = top+0.80, h = 0.75, pitch gap 0.153 (3 cols)
    sy = top + 0.80
    n = len(stages)
    gap = _COL_GAP.get(n, 0.15)
    cw = (13.333 - 2 * M - gap * (n - 1)) / n
    ramps = [GRAD_PRIMARY, GRAD_STAGE2, GRAD_STAGE3]
    for i, st in enumerate(stages):
        x = M + i * (cw + gap)
        _round(slide, x, sy, cw, 0.75, grad=ramps[i % 3], prst="homePlate")
        _tb(slide, x + 0.22, sy, cw - 0.30, 0.75, st["head"], size=12,
            color=WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    cy = sy + 0.92
    ch = 3.39
    for i, st in enumerate(stages):
        x = M + i * (cw + gap)
        _round(slide, x, cy, cw, ch, fill=WHITE, line=DIV, radius=0.06)
        _tb(slide, x + 0.19, cy + 0.17, cw - 0.38, 2.45, st["tasks"], size=10,
            color=INK, bold=True, spacing=1.35)
        ms = st.get("milestone")
        if ms:
            strong = st.get("strong", False)
            _round(slide, x + 0.19, cy + ch - 0.69, cw - 0.38, 0.53,
                   grad=GRAD_PRIMARY if strong else None,
                   fill=None if strong else CHIP, radius=0.08)
            _tb(slide, x + 0.30, cy + ch - 0.69, cw - 0.60, 0.53, "★ " + ms,
                size=10, color=WHITE if strong else INK, bold=True,
                anchor=MSO_ANCHOR.MIDDLE)
    if note:
        _note_bar(slide, note, y=BOT - 0.42, h=0.42)


__all__ = ["content_header", "chapter_page", "toc_page", "four_role_cards",
           "org_chart",
           "two_panel_list", "quad_cards", "column_cards", "stage_cards",
           "STAGE_RAMPS",
           "progress_timeline", "stage_timeline", "STATUS", "GRAD_PRIMARY",
           "GRAD_WARN", "GRAD_PLAN", "GRAD_STAGE2", "GRAD_STAGE3", "FONT",
           "CH_TITLE", "CH_LINE", "CH_LIST", "QUAD_CARD", "QUAD_GAP",
           "QUAD_PITCH_Y", "TOC_DECO", "TOC_TITLE", "TOC_TITLE_EN",
           "TOC_ACCENT", "TOC_NOTE", "TOC_ITEM_X", "TOC_ITEM_Y0",
           "TOC_ITEM_PITCH"]
