"""Narrative Engine -- LLM-first by design, rules as the guaranteed floor.

V2.1 decision (plan §7 / §7.1): narrative planning is an LLM job. But the
LLM arrives through the MCP sampling seam built in batch 3; until -- and
even after -- that exists, this module guarantees a working rules path:

``build_narrative(document, *, llm_fn=None)``

* ``llm_fn=None``              -> rules path, ``metadata.llm = "off"``
* ``llm_fn=prompt->text``      -> try the LLM; on any failure fall back to
  rules with ``metadata.llm = "fallback"``; on success ``"sampled"``

**Execution red line 6: a degraded run is never silent.** Whatever path ran,
``metadata.llm`` states it and the narrative payload carries the honest
story. Batch 3 wires ``llm_fn`` to ``llm.provider.MCPSamplingProvider``.

The rules path classifies level<=2 headings into a four-stage business arc
(context / action / evidence / outlook) by Chinese keyword buckets and
orders sections along it. ``story.py`` remains the md->IR sibling and is
not modified here (355-test baseline safety).
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .content_ir import ContentDocument

SCHEMA = "narrative/v1"

_ARC_BUCKETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # action/evidence/outlook/risk checked BEFORE context: their tokens are the
    # more specific signal ("建设举措" must hit action, not context's "建设")
    ("action", ("措施", "推进", "实施", "工作", "举措", "专项", "整改", "部署")),
    ("evidence", ("成效", "成果", "成绩", "数据", "指标", "评审", "通过", "达成")),
    ("risk", ("问题", "挑战", "风险", "不足", "困难")),
    ("outlook", ("计划", "展望", "下一步", "下阶段", "重点", "规划", "后续")),
    ("context", ("背景", "概况", "现状", "简介", "总体", "项目", "覆盖", "建设")),
)

_ARC_ORDER: tuple[str, ...] = ("context", "action", "evidence", "outlook", "risk")

# a *hard* metric: percentages or multi-digit figures ("99.2%", "1200") --
# single-digit counts ("5 个院区") are not enough to call a section data-driven
_METRIC = re.compile(r"\d+\.\d+%|\d+%|\d{2,}")


def _classify_stage(title: str) -> str:
    for stage, tokens in _ARC_BUCKETS:
        if any(token in title for token in tokens):
            return stage
    return "context"


def build_narrative(
    document: ContentDocument,
    *,
    llm_fn: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Narrative plan over a ContentDocument; LLM optional, fallback mandatory."""
    if llm_fn is not None:
        try:
            llm_text = llm_fn(_build_llm_prompt(document))
        except Exception:  # noqa: BLE001 -- any LLM failure must degrade, never abort
            return _rules_narrative(document, llm="fallback")
        return {
            "schema": SCHEMA,
            "mode": "llm",
            "arc": _llm_arc(llm_text, document),
            "sections": _rules_sections(document),
            "metadata": {"llm": "sampled"},
        }
    return _rules_narrative(document, llm="off")


def _build_llm_prompt(document: ContentDocument) -> str:
    headings = [block.text or "" for block in document.headings()]
    return (
        "请为以下演示文稿章节规划叙事顺序（背景->举措->成效->展望），"
        "仅输出排序后的章节标题列表：\n" + "\n".join(f"- {h}" for h in headings)
    )


def _llm_arc(llm_text: str, document: ContentDocument) -> list[str]:
    """Best-effort: take the LLM's returned heading order; unknown titles keep source order."""
    known = [block.text or "" for block in document.headings()]
    ordered: list[str] = []
    for line in llm_text.splitlines():
        candidate = line.strip().lstrip("-*·0123456789.、） ").strip()
        if candidate in known and candidate not in ordered:
            ordered.append(candidate)
    for title in known:
        if title not in ordered:
            ordered.append(title)
    return ordered


def _rules_narrative(document: ContentDocument, *, llm: str) -> dict[str, Any]:
    sections = _rules_sections(document)
    stages: dict[str, list[dict[str, Any]]] = {}
    for section in sections:
        stages.setdefault(section["stage"], []).append(section)
    arc: list[str] = []
    for stage in _ARC_ORDER:
        for section in stages.get(stage, []):
            arc.append(section["title"])
    return {
        "schema": SCHEMA,
        "mode": "rules",
        "arc": arc,
        "sections": sections,
        "metadata": {"llm": llm, "engine": "rules/keyword-arc"},
    }


def _rules_sections(document: ContentDocument) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for heading, children in document.sections():
        title = heading.text or ""
        stage = _classify_stage(title)
        numbers = sum(
            1
            for block in children
            if _METRIC.search(block.text or " ".join(block.items))
        )
        result.append({
            "title": title,
            "stage": stage,
            "block_count": len(children),
            "metric_blocks": numbers,
            "suggested_emphasis": "data" if numbers >= 1 else "narrative",
        })
    return result
