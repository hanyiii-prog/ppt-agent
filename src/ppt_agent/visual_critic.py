from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from PIL import Image


@dataclass(frozen=True)
class CriticFinding:
    page: int
    severity: str
    rule: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class CriticReport:
    passed: bool
    pages: list[CriticFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "findings": [asdict(item) for item in self.pages]}


class VisualCritic(Protocol):
    def review(self, image: Path, page: int) -> list[CriticFinding]:
        ...


class HeuristicVisualCritic:
    """Deterministic fallback critic used when no multimodal model is available."""

    def __init__(self, *, blank_threshold: float = 0.995, edge_band: int = 3):
        self.blank_threshold = blank_threshold
        self.edge_band = edge_band

    def review(self, image: Path, page: int) -> list[CriticFinding]:
        findings: list[CriticFinding] = []
        with Image.open(image) as im:
            rgb = im.convert("RGB")
            small = rgb.resize((256, 144))
            pixels = list(small.getdata())
            near_white = sum(1 for p in pixels if min(p) >= 250) / len(pixels)
            if near_white >= self.blank_threshold:
                findings.append(CriticFinding(
                    page, "error", "near_blank", "Rendered page is nearly blank",
                    {"near_white_ratio": round(near_white, 6)},
                ))

            width, height = rgb.size
            band = min(self.edge_band, width // 20, height // 20)
            if band:
                px = rgb.load()
                edge_samples = []
                for x in range(width):
                    edge_samples.extend((px[x, y] for y in range(band)))
                    edge_samples.extend((px[x, height - 1 - y] for y in range(band)))
                for y in range(band, height - band):
                    edge_samples.append(px[0, y])
                    edge_samples.append(px[width - 1, y])
                dark_edge = sum(1 for p in edge_samples if max(p) < 12) / max(1, len(edge_samples))
                if dark_edge > 0.98:
                    findings.append(CriticFinding(
                        page, "warning", "edge_black", "Page edge is dominated by near-black pixels",
                        {"dark_edge_ratio": round(dark_edge, 6)},
                    ))

        return findings


def review_pages(rendered_pages: list[Path], critic: VisualCritic | None = None) -> CriticReport:
    critic = critic or HeuristicVisualCritic()
    findings: list[CriticFinding] = []
    for page, image in enumerate(rendered_pages, start=1):
        findings.extend(critic.review(image, page))
    return CriticReport(
        passed=not any(item.severity == "error" for item in findings),
        pages=findings,
    )
