"""Content Analyzer (rules implementation -- deterministic, no LLM).

Input: a ``ContentDocument``. Output: a *deep copy* with, per block, an
``analysis`` dict and, at document level, ``metadata["analyzer"]``:

``analysis.importance``  0-1 salience score (structure/data outrank prose)
``analysis.category``    structure / data / list / metric / quote / narrative
``analysis.keywords``    top terms (CJK bigrams + ASCII words, stopworded)

The LLM path plugs in at batch 3 (narrative_engine's provider seam); when no
LLM is involved the metadata says so -- ``llm: off`` -- and never pretends
otherwise (execution red line 6).
"""

from __future__ import annotations

import copy
import re
from collections import Counter
from typing import Any

from .content_ir import ContentDocument, ContentBlock

STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "by", "as", "at", "this", "that",
    "我们", "你们", "他们", "一个", "以及", "并且", "或者", "通过", "进行",
    "已经", "可以", "这个", "那个", "对于", "关于",
})

_ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{1,}")
_NUMBERISH = re.compile(r"\d+(?:\.\d+)?%?")


def _keywords(text: str, top: int = 3) -> list[str]:
    counter: Counter[str] = Counter()
    for word in _ASCII_WORD.findall(text):
        if word.lower() not in STOPWORDS and len(word) > 1:
            counter[word.lower()] += 1
    cjk_runs = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    for run in cjk_runs:
        for size in (2,):
            for index in range(len(run) - size + 1):
                gram = run[index:index + size]
                if gram not in STOPWORDS:
                    counter[gram] += 1
    return [term for term, _count in counter.most_common(top)]


def _importance(block: ContentBlock, *, after_heading: bool) -> float:
    if block.type == "heading":
        return 0.95 if (block.level or 1) <= 2 else 0.7
    if block.type == "table":
        return 0.85
    if block.type in ("bullets", "ordered"):
        numeric = sum(1 for item in block.items if _NUMBERISH.search(item))
        score = 0.75 if numeric else 0.6
        if len(block.items) >= 4:
            score = min(0.85, score + 0.05)
        return score
    if block.type == "quote":
        return 0.35
    length = len(block.text or "")
    score = 0.4 + min(0.2, length / 1500)
    if _NUMBERISH.search(block.text or ""):
        score = min(0.85, score + 0.15)
    return min(0.9, score + (0.05 if after_heading else 0.0))


def _category(block: ContentBlock) -> str:
    if block.type == "heading":
        return "structure"
    if block.type == "table":
        return "data"
    if block.type in ("bullets", "ordered"):
        if any(_NUMBERISH.search(item) for item in block.items):
            return "metric"
        return "list"
    if block.type == "quote":
        return "quote"
    if _NUMBERISH.search(block.text or ""):
        return "metric"
    return "narrative"


def analyze_content(document: ContentDocument) -> ContentDocument:
    """Return an enriched deep copy; never mutates the input."""
    enriched = copy.deepcopy(document)
    previous_was_heading = False
    for block in enriched.blocks:
        block.analysis = {
            "importance": round(_importance(block, after_heading=previous_was_heading), 3),
            "category": _category(block),
            "keywords": _keywords(
                block.text or " ".join(block.items)
                or " ".join(" ".join(row) for row in block.rows)
            ),
        }
        previous_was_heading = block.type == "heading"
    enriched.metadata["analyzer"] = "rules"
    enriched.metadata["llm"] = "off"
    return enriched
