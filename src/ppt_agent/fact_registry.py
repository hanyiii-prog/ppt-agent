from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .ir import Presentation


def normalize_claim(text: Any) -> str:
    """Normalize a claim so trivial formatting differences do not break matching."""
    return " ".join(str(text or "").lower().split())


@dataclass(frozen=True)
class Fact:
    claim: str
    source_id: str
    locator: str | None = None
    quote: str | None = None


class FactRegistry:
    """A provenance-backed fact store used to catch unsupported or hallucinated claims."""

    def __init__(self, facts: Iterable[Fact] | None = None) -> None:
        self._facts: list[Fact] = list(facts or [])
        self._index: dict[str, Fact] = {}
        for fact in self._facts:
            self._index.setdefault(normalize_claim(fact.claim), fact)

    def register(
        self,
        claim: str,
        *,
        source_id: str,
        locator: str | None = None,
        quote: str | None = None,
    ) -> Fact:
        fact = Fact(claim=str(claim), source_id=str(source_id), locator=locator, quote=quote)
        self._facts.append(fact)
        self._index.setdefault(normalize_claim(fact.claim), fact)
        return fact

    def register_many(
        self,
        claims: Iterable[str],
        *,
        source_id: str,
        locator: str | None = None,
    ) -> list[Fact]:
        return [self.register(claim, source_id=source_id, locator=locator) for claim in claims]

    def find(self, claim: str) -> Fact | None:
        return self._index.get(normalize_claim(claim))

    def is_supported(self, claim: str) -> bool:
        return self.find(claim) is not None

    def unsupported(self, claims: Iterable[str]) -> list[str]:
        return [claim for claim in claims if not self.is_supported(claim)]

    @property
    def facts(self) -> tuple[Fact, ...]:
        return tuple(self._facts)

    def __len__(self) -> int:
        return len(self._facts)

    def to_dict(self) -> dict[str, Any]:
        return {"facts": [asdict(fact) for fact in self._facts]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FactRegistry":
        return cls(Fact(**item) for item in (data.get("facts") or []) if isinstance(item, dict))


def collect_claims(presentation: Presentation) -> list[str]:
    """Collect all non-empty text claims carried by a presentation IR."""
    claims: list[str] = []
    for slide in presentation.slides:
        if slide.claim:
            claims.append(slide.claim)
        for component in slide.components:
            if component.text:
                claims.append(component.text)
    return claims


def audit_presentation(presentation: Presentation, registry: FactRegistry) -> list[dict[str, Any]]:
    """Return a per-claim support report; empty list means every claim is backed by a fact."""
    report: list[dict[str, Any]] = []
    for slide in presentation.slides:
        for component in slide.components:
            text = component.text
            if not text:
                continue
            fact = registry.find(text)
            report.append({
                "slide": slide.id,
                "component": component.id,
                "claim": text,
                "supported": fact is not None,
                "source_id": fact.source_id if fact else None,
                "locator": fact.locator if fact else None,
            })
    return report
