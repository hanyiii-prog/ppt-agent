"""Template fingerprint: a unique identity for one reference PPTX.

Why this exists
---------------
Multiple templates produce their own DNA, component libraries and element
libraries. Without a fingerprint there is nothing preventing a pipeline run
from mixing template A's DNA with template B's component store -- producing
slides that look half-of-each and are impossible to debug.

What this module produces
-------------------------
``compute_template_fingerprint(deck_dna)`` derives a deterministic SHA-256
from the template's identity anchors:

* the slide dimensions (width x height in inches)
* the theme colour scheme (every named colour, sorted by key)
* the theme font scheme (majorFace / minorFace)
* the master/layout shape count per path

The fingerprint is a 12-char hex prefix of the full hash -- short enough to
put in a filename, long enough to be collision-free for real templates.

``check_template_consistency(*payloads)`` verifies that every payload that
claims to come from a template carries the same fingerprint. It raises
``TemplateMismatchError`` when they do not, so the pipeline can refuse
honestly instead of producing a chimera.
"""

from __future__ import annotations

import hashlib
from typing import Any


class TemplateMismatchError(ValueError):
    """Raised when payloads from different templates are mixed."""


def compute_template_fingerprint(deck_dna: dict[str, Any]) -> str:
    """Derive a 12-char hex fingerprint from a template-dna payload."""
    if not isinstance(deck_dna, dict) or "slides" not in deck_dna:
        raise ValueError("compute_template_fingerprint expects a template-dna payload")

    anchors: list[str] = []

    size = (deck_dna.get("presentation") or {}).get("slide_size_inches") or {}
    anchors.append(f"size:{size.get('width')}x{size.get('height')}")

    theme = deck_dna.get("theme") or {}
    colors = theme.get("colors") or {}
    for key in sorted(colors):
        anchors.append(f"color:{key}={colors[key]}")

    fonts = theme.get("font_scheme") or {}
    for face_key in ("majorFace", "minorFace"):
        face = fonts.get(face_key) or {}
        anchors.append(f"font:{face_key}:{face.get('latin')}")

    master_counts: list[str] = []
    for master in deck_dna.get("masters") or []:
        shapes = master.get("shapes") or []
        master_counts.append(f"{master.get('path', '?')}:{len(shapes)}")
    master_counts.sort()
    anchors.extend(f"master:{m}" for m in master_counts)

    raw = "|".join(anchors)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def check_template_consistency(*payloads: dict[str, Any]) -> str:
    """Verify all payloads share the same template_fingerprint; return it.

    Payloads that carry no fingerprint (e.g. a bare ContentDocument) are
    skipped. Raises TemplateMismatchError on the first conflicting pair.
    """
    fingerprints: set[str] = set()
    for payload in payloads:
        fp = (payload or {}).get("template_fingerprint")
        if isinstance(fp, str) and fp:
            fingerprints.add(fp)
    if len(fingerprints) > 1:
        raise TemplateMismatchError(
            f"template fingerprints do not match: {sorted(fingerprints)}; "
            "never mix DNA / components / elements from different templates"
        )
    return next(iter(fingerprints), "")
