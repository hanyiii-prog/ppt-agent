from __future__ import annotations

from typing import Any

from .source_pack import SourcePack
from .evidence_graph import infer_relations

SCHEMA = "content-relations/v1"


def build_content_relations(pack: SourcePack, fact_ids: dict[str, str] | None = None) -> dict[str, Any]:
    relations = infer_relations(pack, fact_ids)
    return {
        "schema": SCHEMA,
        "relations": relations,
        "relation_types": sorted({item["type"] for item in relations}),
    }


__all__ = ["SCHEMA", "build_content_relations"]
