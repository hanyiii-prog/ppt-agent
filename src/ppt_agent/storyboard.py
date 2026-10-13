"""Validated model-authored slide plans with source traceability."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from .content_ir import ContentDocument
from .page_archetype import ARCHETYPES, select_archetype

SCHEMA = "storyboard/v1"
_KINDS = frozenset({"cover", "toc", "section", "content", "closing"})
_LAYOUT_VARIANTS = frozenset({"standard", "split", "wide", "grid", "compact"})
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")

_DEFAULT_PALETTE = {
    "primary": "0B4A42",
    "accent": "D98942",
    "surface": "F5F7F5",
    "panel": "E8EFEC",
    "text": "1F2927",
    "muted": "5D6D68",
    "inverse": "FFFFFF",
}


class StoryboardValidationError(ValueError):
    """The model response cannot safely be used as a presentation plan."""


def _json_payload(text: str) -> dict[str, Any]:
    value = (text or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        value = fenced.group(1)
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise StoryboardValidationError(f"response is not valid JSON: {exc.msg}") from exc
    if not isinstance(result, dict):
        raise StoryboardValidationError("response root must be a JSON object")
    return result


def _palette(value: Any) -> tuple[dict[str, str], list[str]]:
    palette = dict(_DEFAULT_PALETTE)
    warnings: list[str] = []
    if value is None:
        return palette, warnings
    if not isinstance(value, dict):
        return palette, ["design_profile.palette must be an object; defaults were used"]
    for name in palette:
        if name not in value:
            continue
        match = _HEX.fullmatch(str(value[name]).strip())
        if not match:
            warnings.append(f"invalid palette color {name!r}; default was used")
            continue
        palette[name] = match.group(1).upper()
    return palette, warnings


def normalize_storyboard(
    raw: str | dict[str, Any],
    document: ContentDocument,
    *,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate slide order, page budget and complete source-block accounting."""
    payload = _json_payload(raw) if isinstance(raw, str) else raw
    if not isinstance(payload, dict):
        raise StoryboardValidationError("storyboard must be an object")
    if payload.get("schema") not in (None, SCHEMA):
        raise StoryboardValidationError(f"unsupported schema {payload.get('schema')!r}")

    constraints = constraints if isinstance(constraints, dict) else {}
    max_pages = constraints.get("max_pages")
    if max_pages is not None and (
        isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1
    ):
        raise StoryboardValidationError("max_pages must be a positive integer")

    source_ids = {block.id for block in document.blocks}
    slides = payload.get("slides")
    if not isinstance(slides, list) or not slides:
        raise StoryboardValidationError("slides must be a non-empty array")
    if max_pages is not None and len(slides) > max_pages:
        raise StoryboardValidationError(
            f"storyboard has {len(slides)} pages, exceeding max_pages={max_pages}"
        )

    normalized: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, entry in enumerate(slides, start=1):
        if not isinstance(entry, dict):
            raise StoryboardValidationError(f"slides[{index - 1}] must be an object")
        kind = str(entry.get("kind") or "").strip().lower()
        if kind not in _KINDS:
            raise StoryboardValidationError(f"slides[{index - 1}] has unsupported kind {kind!r}")
        title = str(entry.get("title") or "").strip()
        if not title:
            raise StoryboardValidationError(f"slides[{index - 1}] is missing a title")
        refs = entry.get("source_block_ids", [])
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise StoryboardValidationError(
                f"slides[{index - 1}].source_block_ids must be an array of block IDs"
            )
        refs = list(dict.fromkeys(refs))
        unknown = [ref for ref in refs if ref not in source_ids]
        if unknown:
            raise StoryboardValidationError(
                f"slides[{index - 1}] references unknown source block {unknown[0]!r}"
            )
        used_ids.update(refs)

        archetype = str(entry.get("archetype") or "")
        if archetype not in ARCHETYPES:
            archetype = ""
        layout_variant = str(entry.get("layout_variant") or "standard").strip().lower()
        if layout_variant not in _LAYOUT_VARIANTS:
            raise StoryboardValidationError(
                f"slides[{index - 1}] has unsupported layout_variant {layout_variant!r}"
            )
        evidence_ids = _string_list(entry.get("evidence_ids"))
        unknown_evidence = [evidence_id for evidence_id in evidence_ids if evidence_id not in source_ids]
        if unknown_evidence:
            raise StoryboardValidationError(
                f"slides[{index - 1}] references unknown evidence ID {unknown_evidence[0]!r}"
            )
        normalized.append({
            "page_no": index,
            "kind": kind,
            "title": title,
            "source_blocks": refs,
            "key_message": str(entry.get("key_message") or "").strip(),
            "visual_form": str(entry.get("visual_form") or "").strip(),
            "archetype_name": archetype,
            "layout_variant": layout_variant,
            "evidence_ids": evidence_ids or refs,
            "speaker_notes": str(entry.get("speaker_notes") or "").strip() or None,
        })

    omissions = payload.get("omitted_source_blocks", [])
    if not isinstance(omissions, list):
        raise StoryboardValidationError("omitted_source_blocks must be an array")
    normalized_omissions: list[dict[str, str]] = []
    omitted_ids: set[str] = set()
    for index, item in enumerate(omissions):
        if not isinstance(item, dict):
            raise StoryboardValidationError(f"omitted_source_blocks[{index}] must be an object")
        block_id = str(item.get("id") or "")
        reason = str(item.get("reason") or "").strip()
        if block_id not in source_ids:
            raise StoryboardValidationError(f"omission references unknown source block {block_id!r}")
        if block_id in used_ids:
            raise StoryboardValidationError(f"source block {block_id!r} is both used and omitted")
        if not reason:
            raise StoryboardValidationError(f"omitted source block {block_id!r} needs a reason")
        omitted_ids.add(block_id)
        normalized_omissions.append({"id": block_id, "reason": reason})

    unaccounted = source_ids - used_ids - omitted_ids
    if unaccounted:
        block_id = next(block.id for block in document.blocks if block.id in unaccounted)
        raise StoryboardValidationError(
            f"source block {block_id!r} is neither used nor explicitly omitted"
        )

    profile = payload.get("design_profile")
    profile = profile if isinstance(profile, dict) else {}
    typography = profile.get("typography")
    typography = typography if isinstance(typography, dict) else {}
    palette, palette_warnings = _palette(profile.get("palette"))
    task_palette, task_warnings = _palette(constraints.get("palette"))
    if isinstance(constraints.get("palette"), dict):
        palette.update(task_palette)
    visual_direction = str(
        profile.get("visual_direction") or constraints.get("visual_direction") or ""
    ).strip()
    return {
        "schema": SCHEMA,
        "design_profile": {
            "visual_direction": visual_direction,
            "palette": palette,
            "typography": {
                "title_font": str(typography.get("title_font") or "").strip(),
                "body_font": str(typography.get("body_font") or "").strip(),
            },
        },
        "slides": normalized,
        "omitted_source_blocks": normalized_omissions,
        "unmapped_source_block_ids": [],
        "warnings": palette_warnings + task_warnings,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def storyboard_to_plan(
    storyboard: dict[str, Any],
    document: ContentDocument,
    *,
    density: str = "standard",
) -> dict[str, Any]:
    """Translate the validated model contract into the shared planner contract."""
    lookup = {block.id: block for block in document.blocks}
    pages: list[dict[str, Any]] = []
    for index, slide in enumerate(storyboard["slides"], start=1):
        blocks = [lookup[block_id] for block_id in slide["source_blocks"]]
        archetype_name = slide.get("archetype_name")
        archetype = (
            {"schema": "archetype/v1", "archetype": archetype_name,
             "confidence": 0.9, "reason": "selected by the storyboard model"}
            if archetype_name
            else select_archetype(blocks)
        )
        pages.append({
            "page_no": index,
            "kind": slide["kind"],
            "title": slide["title"],
            "source_blocks": list(slide["source_blocks"]),
            "key_message": slide.get("key_message") or "",
            "visual_form": slide.get("visual_form") or "",
            "layout_variant": slide.get("layout_variant") or "standard",
            "evidence_ids": list(slide.get("evidence_ids") or []),
            "speaker_notes": slide.get("speaker_notes"),
            "archetype": archetype if slide["kind"] == "content" else None,
        })
    return {
        "schema": "presentation-plan/v1",
        "density": density,
        "pages": pages,
        "page_total": len(pages),
        "design_profile": storyboard.get("design_profile") or {},
        "omitted_source_blocks": storyboard.get("omitted_source_blocks") or [],
        "metadata": {"llm": "sampled", "planner": "storyboard"},
    }


def build_storyboard(
    document: ContentDocument,
    *,
    llm_fn: Callable[[str], str] | None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask the model for a constrained storyboard; report honest fallback state."""
    if llm_fn is None:
        return {"storyboard": None, "metadata": {"llm": "off"}, "error": None}
    try:
        prompt = _build_prompt(document, constraints or {})
        raw_response = llm_fn(prompt)
        storyboard = normalize_storyboard(raw_response, document, constraints=constraints)
    except Exception as exc:  # a malformed model response must not stop delivery
        return {
            "storyboard": None,
            "metadata": {"llm": "fallback"},
            "error": f"{type(exc).__name__}: {exc}",
            "raw_response": locals().get("raw_response"),
        }
    return {
        "storyboard": storyboard,
        "metadata": {"llm": "sampled"},
        "error": None,
        "raw_response": raw_response,
    }


def _build_prompt(document: ContentDocument, constraints: dict[str, Any]) -> str:
    blocks = []
    for block in document.blocks:
        item = {"id": block.id, "type": block.type}
        if block.text:
            item["text"] = block.text
        if block.items:
            item["items"] = block.items
        if block.headers:
            item["headers"] = block.headers
            item["rows"] = block.rows
        blocks.append(item)
    return (
        "为演示文稿设计可直接生成的逐页故事板。先确定受众、目标和叙事，再按内容选择每页的信息结构；"
        "不要套用固定视觉模板。视觉方向应克制但有辨识度，跨页可变化但保持一致；优先使用可编辑的原生图表、"
        "时间线、对比、指标和卡片结构。只使用给定来源中的事实，不要发明数字、因果或承诺。\n"
        "必须只输出一个 JSON 对象，禁止 Markdown 围栏。结构："
        '{"schema":"storyboard/v1","design_profile":{"visual_direction":"...","typography":{"title_font":"...","body_font":"..."},"palette":'
        '{"primary":"RRGGBB","accent":"RRGGBB","surface":"RRGGBB","panel":"RRGGBB","text":"RRGGBB",'
        '"muted":"RRGGBB","inverse":"RRGGBB"}},"slides":[{"kind":"cover|toc|section|content|closing",'
        '"title":"...","key_message":"...","source_block_ids":["原始 block id"],"visual_form":"...","archetype":'
        '"title_bullets|cards_grid|metrics_row|table_page|timeline|comparison|narrative|quote_strip",'
        '"layout_variant":"standard|split|wide|grid|compact","evidence_ids":["source block ID"],'
        '"speaker_notes":"..."}],"omitted_source_blocks":[{"id":"...","reason":"..."}]}.\n'
        "每个原始 block ID 必须至少出现在一个页面的 source_block_ids 中；确需删去的内容必须逐项列在 "
        "omitted_source_blocks 并解释原因。页面标题可以提炼，但其依据要包含在 source_block_ids 中。"
        "evidence_ids（若提供）必须与来源 block ID 完全一致。max_pages 是硬上限。"
        "palette 必须满足文本对比度。逐页选择 layout_variant；内容结构不同就不要重复同一种构图。\n"
        f"用户任务约束：{json.dumps(constraints, ensure_ascii=False, separators=(',', ':'))}\n"
        f"文档标题：{document.title or ''}\n"
        f"来源内容块：{json.dumps(blocks, ensure_ascii=False, separators=(',', ':'))}"
    )


__all__ = [
    "SCHEMA",
    "StoryboardValidationError",
    "build_storyboard",
    "normalize_storyboard",
    "storyboard_to_plan",
]
