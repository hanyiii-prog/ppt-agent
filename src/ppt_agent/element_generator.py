"""Element generation: rules first, LLM as a bounded fallback.

When the element store misses, this module generates the element. The
strategy ladder is:

1. ``rules``   -- deterministic builders for the known element types
                  (title, body, bullet_list, card_frame, divider, quote).
                  These cover the vast majority of slides; zero tokens.
2. ``llm``     -- only when the element type is unknown or the rules builder
                  raises. Uses the ``llm_fn`` seam (which may itself fall
                  back to rules at the narrative level). Every LLM call is
                  disclosed in the returned metadata.
3. ``fail``    -- if no llm_fn is provided and rules cannot handle the type,
                  the module returns a minimal honest placeholder.

Every element returned by ``generate_element`` is stored in the element
store by the caller, so the same fingerprint will hit on the next run.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from . import element_store


def generate_element(
    spec: dict[str, Any],
    *,
    llm_fn: Callable[[str], str] | None = None,
    template_fingerprint: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One element spec -> (element dict, metadata).

    ``spec`` carries at minimum ``type`` and ``text`` (or ``items``). Returns
    metadata with ``generator`` in {"rules","llm","placeholder"} and
    ``tokens_estimate`` (0 for rules, >0 for LLM).
    """
    element_type = str(spec.get("type") or "body").lower()

    try:
        element = _rules_build(spec, element_type)
        return element, {"generator": "rules", "tokens_estimate": 0}
    except (ValueError, KeyError):
        pass

    if llm_fn is not None:
        try:
            element = _llm_build(spec, llm_fn)
            return element, {"generator": "llm", "tokens_estimate": _estimate_tokens(spec)}
        except Exception:
            pass

    element = _placeholder(spec, element_type)
    return element, {"generator": "placeholder", "tokens_estimate": 0}


def generate_with_cache(
    spec: dict[str, Any],
    *,
    llm_fn: Callable[[str], str] | None = None,
    template_fingerprint: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """generate_element + element store cache. Returns (element, metadata).

    Metadata includes ``cache`` in {"hit","miss"} and ``fingerprint``.
    On a hit the element is returned directly (zero generation cost).
    On a miss the element is generated and stored for next time.
    """
    fp = element_store.fingerprint_element(spec)
    cached = element_store.lookup(fp)
    if cached is not None:
        element_store.increment_usage(fp)
        return dict(cached.get("element") or {}), {
            "generator": "cache", "cache": "hit", "fingerprint": fp, "tokens_estimate": 0,
        }

    element, meta = generate_element(
        spec, llm_fn=llm_fn, template_fingerprint=template_fingerprint
    )
    element_store.store(fp, element, source_fingerprint=template_fingerprint)
    meta["cache"] = "miss"
    meta["fingerprint"] = fp
    return element, meta


# -- rules builders ----------------------------------------------------------

def _rules_build(spec: dict[str, Any], element_type: str) -> dict[str, Any]:
    builders = {
        "title": _build_title,
        "subtitle": _build_subtitle,
        "body": _build_body,
        "bullet_list": _build_bullet_list,
        "card": _build_card,
        "divider": _build_divider,
        "quote": _build_quote,
        "table": _build_table,
        "image": _build_image,
        "metric": _build_metric,
        "timeline_item": _build_timeline_item,
    }
    builder = builders.get(element_type)
    if builder is None:
        raise ValueError(f"no rules builder for type {element_type!r}")
    return builder(spec)


def _build_title(spec: dict[str, Any]) -> dict[str, Any]:
    text = str(spec.get("text") or "").strip()
    if not text:
        raise ValueError("title requires text")
    return {"type": "title", "text": text, "font_pt": spec.get("font_pt") or 28.0}


def _build_subtitle(spec: dict[str, Any]) -> dict[str, Any]:
    text = str(spec.get("text") or "").strip()
    if not text:
        raise ValueError("subtitle requires text")
    return {"type": "subtitle", "text": text, "font_pt": spec.get("font_pt") or 18.0}


def _build_body(spec: dict[str, Any]) -> dict[str, Any]:
    text = str(spec.get("text") or "").strip()
    if not text:
        raise ValueError("body requires text")
    return {"type": "body", "text": text, "font_pt": spec.get("font_pt") or 14.0}


def _build_bullet_list(spec: dict[str, Any]) -> dict[str, Any]:
    items = spec.get("items") or []
    if not items:
        raise ValueError("bullet_list requires items")
    return {"type": "body", "text": "\n".join(f"- {item}" for item in items), "font_pt": 14.0}


def _build_card(spec: dict[str, Any]) -> dict[str, Any]:
    text = str(spec.get("text") or "").strip()
    if not text:
        raise ValueError("card requires text")
    return {"type": "card", "text": text, "font_pt": 14.0, "rounded": True}


def _build_divider(spec: dict[str, Any]) -> dict[str, Any]:
    return {"type": "decoration", "shape": "line", "font_pt": 0, "text": None}


def _build_quote(spec: dict[str, Any]) -> dict[str, Any]:
    text = str(spec.get("text") or "").strip()
    if not text:
        raise ValueError("quote requires text")
    return {"type": "quote", "text": text, "font_pt": 18.0, "italic": True}


def _build_table(spec: dict[str, Any]) -> dict[str, Any]:
    headers = spec.get("headers") or []
    rows = spec.get("rows") or []
    if not rows:
        raise ValueError("table requires rows")
    return {"type": "table", "text": "\n".join(headers), "data": {"headers": headers, "rows": rows}}


def _build_image(spec: dict[str, Any]) -> dict[str, Any]:
    path = str(spec.get("image_path") or "").strip()
    if not path:
        raise ValueError("image requires image_path")
    return {"type": "image", "image_path": path, "text": None}


def _build_metric(spec: dict[str, Any]) -> dict[str, Any]:
    value = str(spec.get("value") or "").strip()
    label = str(spec.get("label") or "").strip()
    if not value:
        raise ValueError("metric requires value")
    return {"type": "metric", "text": value, "label": label, "font_pt": 36.0}


def _build_timeline_item(spec: dict[str, Any]) -> dict[str, Any]:
    text = str(spec.get("text") or "").strip()
    marker = str(spec.get("marker") or "").strip()
    if not text:
        raise ValueError("timeline_item requires text")
    return {"type": "body", "text": f"{marker} {text}".strip(), "font_pt": 14.0}


# -- LLM fallback ------------------------------------------------------------

def _llm_build(spec: dict[str, Any], llm_fn: Callable[[str], str]) -> dict[str, Any]:
    prompt = (
        "Generate a single presentation element as JSON. "
        f"Type: {spec.get('type')}. "
        f"Text: {spec.get('text')}. "
        f"Items: {spec.get('items')}. "
        "Return only the JSON object with keys: type, text, font_pt. "
        "No markdown fences, no explanation."
    )
    raw = llm_fn(prompt)
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict) or not parsed.get("type"):
        raise ValueError("LLM returned invalid element JSON")
    return parsed


def _estimate_tokens(spec: dict[str, Any]) -> int:
    text = str(spec.get("text") or "") + str(spec.get("items") or "")
    return max(1, len(text) // 3)


def _placeholder(spec: dict[str, Any], element_type: str) -> dict[str, Any]:
    text = str(spec.get("text") or spec.get("label") or "")
    return {"type": element_type, "text": text, "font_pt": 14.0, "_placeholder": True}
