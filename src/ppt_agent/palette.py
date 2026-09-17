# -*- coding: utf-8 -*-
"""palette -- what the deck *looks* like, not what the XML literally says.

Bug this fixes
--------------
A deck's visible dominant colour is usually carried by ``schemeClr`` references
(the theme's accent1) spread over large areas -- header bars, card fills,
table headers. Counting literal ``srgbClr`` values instead says the opposite:
in the 天津市口腔医院 template the purple ``7030A0`` appears 34 times as a hard
code while the blue theme accent ``1185FE`` appears via ``accent1`` hundreds
of times across 510 in^2 of fills. A count-of-literals "DNA" therefore picked
purple as the brand colour; a human opening the file sees blue. The generated
deck fought its own template chrome (blue header bars, purple cards).

``dominant_colors`` resolves ``schemeClr`` through the theme, weights every
coloured area by its physical size, and buckets by hue family -- reproducing
what the eye reports.
"""
from __future__ import annotations

import colorsys
import re
import zipfile
from collections import defaultdict
from typing import Any

__all__ = ["dominant_colors", "hue_family", "resolve_scheme"]

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS = {"a": _A}
_EMU2IN = 914400.0

_THEME_SLOT_TAGS = ("dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3",
                    "accent4", "accent5", "accent6", "hlink", "folHlink")

#: scheme color slot -> theme clrScheme child (tx1/bg1 are dk1/lt1 aliases)
_SLOT_MAP = {
    "tx1": "dk1", "bg1": "lt1", "tx2": "dk2", "bg2": "lt2",
    "dk1": "dk1", "lt1": "lt1", "dk2": "dk2", "lt2": "lt2",
    "accent1": "accent1", "accent2": "accent2", "accent3": "accent3",
    "accent4": "accent4", "accent5": "accent5", "accent6": "accent6",
    "hlink": "hlink", "folHlink": "folHlink",
}

# lumMod / lumOff percentage adjust (simple HSV value/shift approximation)
_RE_MOD = re.compile(r"<a:lumMod val=\"(\d+)\"")
_RE_OFF = re.compile(r"<a:lumOff val=\"(\d+)\"")


def _theme_slots(theme_xml: str) -> dict[str, str]:
    out: dict[str, str] = {}
    m = re.search(r"<a:clrScheme.*?</a:clrScheme>", theme_xml, re.S)
    seg = m.group(0) if m else theme_xml
    for tag in _THEME_SLOT_TAGS:
        mm = re.search(
            r"<a:%s>\s*<a:(?:srgbClr val=\"([0-9A-Fa-f]{6})\"|sysClr[^>]*lastClr=\"([0-9A-Fa-f]{6})\")" % tag,
            seg)
        if mm:
            out[tag] = (mm.group(1) or mm.group(2)).upper()
    return out


def resolve_scheme(slot: str, theme: dict[str, str],
                   xml_frag: str = "") -> str | None:
    """theme slot name -> 6-hex, applying lumMod/lumOff if present."""
    base = theme.get(_SLOT_MAP.get(slot, slot))
    if not base:
        return None
    mod = _RE_MOD.search(xml_frag)
    off = _RE_OFF.search(xml_frag)
    if not mod and not off:
        return base
    r, g, b = (int(base[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if mod:
        v *= int(mod.group(1)) / 100000.0
    if off:
        v = min(1.0, v + int(off.group(1)) / 100000.0)
    r, g, b = colorsys.hsv_to_rgb(h, s, max(0.0, min(1.0, v)))
    return "%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def hue_family(hex6: str) -> str | None:
    if not hex6 or len(hex6) != 6:
        return None
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if v < 0.16:
        return "near-black"
    if s < 0.12:
        return "white/grey"
    deg = h * 360
    if deg < 15 or deg >= 345:
        return "red"
    if deg < 45:
        return "orange"
    if deg < 70:
        return "yellow"
    if deg < 160:
        return "green"
    if deg < 200:
        return "cyan"
    if deg < 255:
        return "blue"
    if deg < 290:
        return "violet"
    return "magenta/pink"


_GRAD_RE = re.compile(r"<a:gradFill[^>]*>.*?</a:gradFill>", re.S)
_SOLID_SRGB = "<a:solidFill><a:srgbClr val=\"%s\""
_SOLID_SCHEME = "<a:solidFill><a:schemeClr val=\"%s\""


def _area_of(xfrm_match: "re.Match | None") -> float:
    if not xfrm_match:
        return 0.0
    frag = xfrm_match.group(0)
    try:
        ext = re.search(r"<a:ext cx=\"(\d+)\" cy=\"(\d+)\"", frag)
        if not ext:
            ext = re.search(r"<a:ext[^>]*cx=\"(\d+)\"[^>]*cy=\"(\d+)\"", frag)
        if not ext:
            return 0.0
        w = int(ext.group(1)) / _EMU2IN
        h = int(ext.group(2)) / _EMU2IN
        # a 1pt rule is visual filler, not colour area
        return max(0.0, w) * max(0.0, h)
    except (TypeError, ValueError):
        return 0.0


def dominant_colors(pptx_path: str, *, slides_only: bool = False,
                    include_neutrals: bool = False) -> dict[str, Any]:
    """Rank colours by area * visual weight across the whole deck.

    Returns ``{theme, primary, colors:[{rgb, family, area, n}], families:[...]}``.
    ``primary`` is the top non-neutral hue family's top colour -- the brand
    colour a human would name.
    """
    with zipfile.ZipFile(pptx_path) as zf:
        themes = [n for n in zf.namelist() if re.search(r"theme\d+\.xml$", n)]
        theme = _theme_slots(zf.read(themes[0]).decode("utf-8", "ignore")) \
            if themes else {}
        parts = [n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)]
        if not slides_only:
            parts += [n for n in zf.namelist()
                      if re.match(r"ppt/slideLayouts/slideLayout\d+\.xml$", n)]
        area: dict[str, float] = defaultdict(float)
        n_seen: dict[str, int] = defaultdict(int)

        for part in parts:
            xml = zf.read(part).decode("utf-8", "ignore")
            # split into shape-ish chunks so a colour is tied to its geometry
            for sp in re.finditer(r"<a:graphicFrame>.*?</a:graphicFrame>|<p:sp>.*?</p:sp>",
                                  xml, re.S):
                frag = sp.group(0)
                xfrm = re.search(r"<a:xfrm[^>]*>(?:(?!</a:xfrm>).)*?</a:xfrm>", frag, re.S)
                a = _area_of(xfrm) if xfrm else 0.0
                if a <= 0.0:
                    continue
                # solid fill of the shape body (first solidFill wins; line-only
                # shapes contribute a fraction of their area)
                body = re.sub(r"<a:ln[ >].*?</a:ln>", "", frag, flags=re.S)
                m = re.search(_SOLID_SRGB.replace("%s", "([0-9A-Fa-f]{6})"), body)
                rgb = None
                if m:
                    rgb = m.group(1).upper()
                else:
                    ms = re.search(_SOLID_SCHEME.replace("%s", "(\\w+)"), body)
                    if ms:
                        rgb = resolve_scheme(ms.group(1), theme,
                                             frag[max(0, ms.start() - 2):ms.end() + 120])
                if rgb:
                    area[rgb] += a
                    n_seen[rgb] += 1
                # gradient: credit each stop by average weight
                for gfrag in _GRAD_RE.findall(body):
                    stops = re.findall(r"srgbClr val=\"([0-9A-Fa-f]{6})\"", gfrag)
                    sch = re.findall(r"<a:gs[^>]*><a:schemeClr val=\"(\w+)\"", gfrag)
                    cols = [s.upper() for s in stops]
                    for sc in sch:
                        c = resolve_scheme(sc, theme, gfrag)
                        if c:
                            cols.append(c)
                    if cols:
                        w = a / len(cols)
                        for c in cols:
                            area[c] += w
                            n_seen[c] += 1

    colors = []
    for rgb, av in sorted(area.items(), key=lambda e: -e[1]):
        fam = hue_family(rgb)
        if not include_neutrals and fam in ("near-black", "white/grey"):
            continue
        colors.append({"rgb": rgb, "family": fam, "area": round(av, 2),
                       "n": n_seen[rgb]})
    fam_area: dict[str, float] = defaultdict(float)
    for c in colors:
        if c["family"]:
            fam_area[c["family"]] += c["area"]
    families = sorted(fam_area.items(), key=lambda e: -e[1])
    primary = families[0][0] if families else None
    primary_rgb = next((c["rgb"] for c in colors if c["family"] == primary), None) \
        if primary else None
    return {"theme": theme, "primary": primary, "primary_rgb": primary_rgb,
            "families": [{"family": f, "area": round(a, 2)} for f, a in families],
            "colors": colors[:20]}
