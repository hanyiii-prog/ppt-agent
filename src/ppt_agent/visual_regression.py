"""Visual Diff 2.0: rendered fidelity with explicit status and region gates.

Four states exist and are never conflated:

``visual_pass``          every page matched within thresholds
``visual_fail``          rendered pages differed beyond thresholds
``renderer_unavailable`` no rasterisation backend is installed
``renderer_error``       an installed backend failed during conversion

A renderer problem is NEVER a visual pass. On top of the whole-page pixel
diff (MAE / mismatch / SSIM / edge diff), the comparison is computed per
region (background / header / title / body / footer / image / decoration /
chrome) so a tiny-but-critical failure (a lost logo, a shifted title) cannot
hide behind a high whole-page SSIM. ``page_score`` and
``critical_region_score`` quantify both views and feed the Critical Region
Gate.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping


class VisualGateUnavailable(RuntimeError):
    """Raised only when no supported rasterisation backend is installed."""


@dataclass
class PageMetrics:
    page: int
    reference: str
    candidate: str
    width: int
    height: int
    mae: float
    mismatch_ratio: float
    ssim: float
    passed: bool
    diff_image: str | None = None
    candidate_width: int | None = None
    candidate_height: int | None = None
    dimension_match: bool = True
    edge_diff: float = 0.0


@dataclass
class RegionMetrics:
    region: str
    mae: float
    ssim: float
    mismatch: float
    edge_diff: float
    score: float
    passed: bool
    critical: bool = False


@dataclass
class VisualReport:
    passed: bool
    page_count_reference: int
    page_count_candidate: int
    threshold_ssim: float
    threshold_mae: float
    threshold_mismatch: float
    pages: list[PageMetrics]
    status: str = "visual_pass"
    page_score: float = 1.0
    critical_region_score: float = 1.0
    region_metrics: list[RegionMetrics] = field(default_factory=list)
    critical_gate_passed: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise RuntimeError(f"required executable not found: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{detail}") from exc


OFFICE_BINARIES: tuple[str, ...] = ("libreoffice", "soffice")


def office_binary() -> str | None:
    """Absolute path of the LibreOffice/soffice executable, or None."""
    for name in OFFICE_BINARIES:
        found = shutil.which(name)
        if found:
            return found
    return None


def rasteriser_tools() -> tuple[str, ...]:
    """Which rasterisation tools are reachable on this host."""
    return tuple(name for name in (*OFFICE_BINARIES, "pdftoppm") if shutil.which(name))


def preview_backend() -> str | None:
    """Which rasterisation backend can actually run here, real engines first.

    ``powerpoint`` (the ground truth the user sees) then ``libreoffice`` then the
    Pillow approximation. A real backend always wins because Pillow cannot
    reproduce master backgrounds, full-bleed images or picture crops, so visual
    checks made from it are unreliable (see :mod:`ppt_agent.render_real`).
    """
    from . import render_real

    if render_real.powerpoint_available():
        return "powerpoint"
    if office_binary() is not None and shutil.which("pdftoppm") is not None:
        return "libreoffice"
    try:
        import PIL.Image  # noqa: F401
    except Exception:  # pragma: no cover - depends on the environment
        return None
    return "pillow"


def rasteriser_available() -> bool:
    """True when a deck can actually be rasterised on this host."""
    return preview_backend() is not None


def flatten_pixels(image: "Image.Image") -> list:
    """Read every pixel as a flat sequence."""
    getter = getattr(image, "get_flattened_data", None)
    if callable(getter):
        return list(getter())
    return list(image.getdata())


def _prepare_output_dir(output_dir: Path) -> None:
    if output_dir.exists():
        for child in output_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    else:
        output_dir.mkdir(parents=True, exist_ok=True)


def render_pptx(pptx: Path, output_dir: Path, dpi: int = 144, *, allow_approximate: bool = False) -> list[Path]:
    """Render a PPTX to one PNG per slide, real engines first.

    PowerPoint (native, the ground truth the user sees) and LibreOffice reproduce
    master backgrounds, full-bleed images and picture crops faithfully. The
    Pillow approximation is used only when no real backend exists AND the caller
    opts in via ``allow_approximate``: visual gates must never be judged from a
    render that cannot reproduce the template (see :mod:`ppt_agent.render_real`).
    """
    pptx = Path(pptx)  # accept str paths: the libreoffice branch uses pptx.stem
    backend = preview_backend()
    if backend is None:
        raise VisualGateUnavailable(
            "no rasteriser available: install PowerPoint or LibreOffice "
            "(soffice + pdftoppm) to enable visual gates"
        )
    _prepare_output_dir(output_dir)

    if backend == "powerpoint":
        from . import render_real

        pages = sorted(render_real.rasterize_with_powerpoint(
            pptx, output_dir, dpi=float(dpi), prefix="slide"))
    elif backend == "libreoffice":
        binary = office_binary()
        with tempfile.TemporaryDirectory(prefix="ppt-agent-render-") as tmp:
            tmp_path = Path(tmp)
            _run([binary, "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(pptx)])
            pdf = tmp_path / f"{pptx.stem}.pdf"
            if not pdf.exists():
                raise RuntimeError(f"LibreOffice did not produce PDF for {pptx}")
            _run(["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(output_dir / "slide")])
        pages = sorted(output_dir.glob("slide-*.png"))
    else:  # backend == "pillow": an approximation, never silently for gates
        if not allow_approximate:
            raise VisualGateUnavailable(
                "only the Pillow approximation is available; refusing to judge "
                "visual fidelity from a hand-painted render"
            )
        from .preview import rasterize_pptx

        pages = sorted(rasterize_pptx(pptx, output_dir, dpi=float(dpi), prefix="slide"))

    if not pages:
        raise RuntimeError(f"no rendered pages found for {pptx}")
    return pages


# --------------------------------------------------------------------------- #
# pixel comparison primitives
# --------------------------------------------------------------------------- #
def _to_gray_array(path: Path, size: tuple[int, int] | None = None):
    import numpy as np
    from PIL import Image

    with Image.open(path) as im:
        image = im.convert("L")
        if size and image.size != size:
            image = image.resize(size, Image.Resampling.LANCZOS)
        return np.asarray(image, dtype=np.float32) / 255.0


def _block_ssim(a, b, block: int = 8) -> float:
    import numpy as np

    h = min(a.shape[0], b.shape[0]); w = min(a.shape[1], b.shape[1])
    h -= h % block; w -= w % block
    if h == 0 or w == 0:
        return 0.0
    a = a[:h, :w].reshape(h // block, block, w // block, block)
    b = b[:h, :w].reshape(h // block, block, w // block, block)
    mu_a = a.mean(axis=(1, 3)); mu_b = b.mean(axis=(1, 3))
    var_a = a.var(axis=(1, 3)); var_b = b.var(axis=(1, 3))
    cov = ((a - mu_a[:, None, :, None]) * (b - mu_b[:, None, :, None])).mean(axis=(1, 3))
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    score = ((2 * mu_a * mu_b + c1) * (2 * cov + c2) /
             ((mu_a**2 + mu_b**2 + c1) * (var_a + var_b + c2)))
    return float(np.clip(score, 0, 1).mean())


def edge_diff(a, b) -> float:
    """Mean absolute difference of gradient magnitudes, in [0, 1]."""
    import numpy as np

    def grad(img):
        gx = np.abs(np.diff(img, axis=1))
        gy = np.abs(np.diff(img, axis=0))
        return gx, gy

    gx_a, gy_a = grad(a)
    gx_b, gy_b = grad(b)
    h = min(gx_a.shape[0], gx_b.shape[0])
    w = min(gx_a.shape[1], gx_b.shape[1])
    dh = min(gy_a.shape[0], gy_b.shape[0])
    dw = min(gy_a.shape[1], gy_b.shape[1])
    if h == 0 or w == 0 or dh == 0 or dw == 0:
        return 0.0
    diff_x = float(np.abs(gx_a[:h, :w] - gx_b[:h, :w]).mean())
    diff_y = float(np.abs(gy_a[:dh, :dw] - gy_b[:dh, :dw]).mean())
    return round(min(1.0, (diff_x + diff_y) / 2.0), 6)


def compare_images(reference: Path, candidate: Path, *, threshold_ssim: float = 0.995,
                   threshold_mae: float = 0.005, threshold_mismatch: float = 0.01,
                   diff_output: Path | None = None) -> tuple[float, float, float, bool]:
    from PIL import Image, ImageChops, ImageStat
    import numpy as np

    with Image.open(reference) as ref_im, Image.open(candidate) as cand_im:
        ref = ref_im.convert("RGB"); cand = cand_im.convert("RGB")
        dimensions_match = ref.size == cand.size
        if not dimensions_match:
            cand = cand.resize(ref.size, Image.Resampling.LANCZOS)
        diff = ImageChops.difference(ref, cand)
        mae = sum(ImageStat.Stat(diff).mean) / (3 * 255)
        mismatch = float(np.any(np.asarray(diff, dtype=np.uint8) > 8, axis=2).mean())
    gray_ref = _to_gray_array(reference)
    gray_cand = _to_gray_array(candidate, (gray_ref.shape[1], gray_ref.shape[0]))
    ssim = _block_ssim(gray_ref, gray_cand)
    passed = dimensions_match and ssim >= threshold_ssim and mae <= threshold_mae and mismatch <= threshold_mismatch
    if diff_output:
        diff_output.parent.mkdir(parents=True, exist_ok=True)
        diff.point(lambda p: min(255, p * 4)).save(diff_output)
    return mae, mismatch, ssim, passed


# --------------------------------------------------------------------------- #
# region-aware comparison
# --------------------------------------------------------------------------- #
# default bands are vertical fractions of the page (x, y, w, h)
DEFAULT_REGIONS: dict[str, tuple[float, float, float, float]] = {
    "background": (0.0, 0.0, 1.0, 1.0),
    "header": (0.0, 0.0, 1.0, 0.08),
    "title": (0.0, 0.08, 1.0, 0.12),
    "body": (0.0, 0.20, 1.0, 0.68),
    "footer": (0.0, 0.88, 1.0, 0.12),
    "chrome": (0.0, 0.0, 1.0, 0.08),
}
CRITICAL_REGIONS: tuple[str, ...] = ("logo", "title", "image", "decoration", "header", "footer")
CRITICAL_THRESHOLDS = {"ssim": 0.98, "mae": 0.02, "mismatch": 0.05, "edge_diff": 0.05}
_MAE_CAP = 0.05
_MISMATCH_CAP = 0.10
_SSIM_FLOOR = 0.95


def region_score(mae: float, mismatch: float, ssim: float) -> float:
    """Deterministic 0..1 score from the three whole-region metrics."""
    penalty = (min(1.0, mae / _MAE_CAP) * 0.4
               + min(1.0, mismatch / _MISMATCH_CAP) * 0.4
               + (min(1.0, max(0.0, 1.0 - ssim) / max(0.001, 1.0 - _SSIM_FLOOR))) * 0.2)
    return round(max(0.0, 1.0 - penalty), 4)


def _region_metrics(ref_gray, cand_gray, ref_rgb_diff, box, region: str) -> "RegionMetrics":
    import numpy as np

    height, width = ref_gray.shape
    x, y, w, h = box
    x0 = int(round(x * width)); y0 = int(round(y * height))
    x1 = min(width, x0 + int(round(w * width))); y1 = min(height, y0 + int(round(h * height)))
    x1 = max(x1, x0 + 1); y1 = max(y1, y0 + 1)
    ref_crop = ref_gray[y0:y1, x0:x1]
    cand_crop = cand_gray[y0:y1, x0:x1]
    mae = float(np.abs(ref_crop - cand_crop).mean())
    ssim = _block_ssim(ref_crop, cand_crop)
    mismatch = float(ref_rgb_diff[y0:y1, x0:x1].mean())
    edge = edge_diff(ref_crop, cand_crop)
    critical = region in CRITICAL_REGIONS
    thresholds = CRITICAL_THRESHOLDS if critical else {"ssim": 0.95, "mae": 0.05, "mismatch": 0.10, "edge_diff": 0.15}
    passed = (ssim >= thresholds["ssim"] and mae <= thresholds["mae"]
              and mismatch <= thresholds["mismatch"] and edge <= thresholds["edge_diff"])
    return RegionMetrics(
        region=region,
        mae=round(mae, 6),
        ssim=round(ssim, 6),
        mismatch=round(mismatch, 6),
        edge_diff=edge,
        score=region_score(round(mae, 6), round(mismatch, 6), round(ssim, 6)),
        passed=passed,
        critical=critical,
    )


def compare_page_regions(reference: Path, candidate: Path, *, regions: Mapping[str, tuple[float, float, float, float]] | None = None) -> list[RegionMetrics]:
    """Per-region MAE/SSIM/mismatch/edge comparison of two rendered pages."""
    from PIL import Image, ImageChops
    import numpy as np

    region_boxes = dict(regions) if regions else dict(DEFAULT_REGIONS)
    with Image.open(reference) as ref_im, Image.open(candidate) as cand_im:
        ref_rgb = np.asarray(ref_im.convert("RGB"), dtype=np.int16)
        cand_rgb = np.asarray(cand_im.convert("RGB").resize(ref_im.size, Image.Resampling.LANCZOS), dtype=np.int16)
    channel_diff = np.abs(ref_rgb - cand_rgb).max(axis=2) > 8
    ref_gray = _to_gray_array(reference)
    cand_gray = _to_gray_array(candidate, (ref_gray.shape[1], ref_gray.shape[0]))
    return [
        _region_metrics(ref_gray, cand_gray, channel_diff, region_boxes[name], name)
        for name in sorted(region_boxes)
    ]


def regions_from_fidelity(slide_fidelity: Any, page_size: dict[str, int]) -> dict[str, tuple[float, float, float, float]]:
    """Derive region boxes (normalized) from a canonical SlideFidelity model.

    Pictures map to ``image``, title placeholders to ``title``, logo-named
    elements to ``logo`` and decorative bands/waves to ``decoration``; the
    remaining slots keep the default layout bands.
    """
    boxes = dict(DEFAULT_REGIONS)
    page_w = float(page_size.get("width") or 0)
    page_h = float(page_size.get("height") or 0)
    if page_w <= 0 or page_h <= 0:
        return boxes

    def norm(bbox: dict[str, Any]) -> tuple[float, float, float, float] | None:
        try:
            x = float(bbox.get("x", 0)) / page_w
            y = float(bbox.get("y", 0)) / page_h
            w = float(bbox.get("cx", 0)) / page_w
            h = float(bbox.get("cy", 0)) / page_h
        except (TypeError, ValueError):
            return None
        if w <= 0 or h <= 0:
            return None
        return (max(0.0, x), max(0.0, y), min(1.0, w), min(1.0, h))

    for layer in getattr(slide_fidelity, "rendered_layers", []):
        geometry = getattr(layer, "geometry", None) or {}
        bbox = geometry.get("rendered_bbox") if geometry else None
        if not bbox:
            continue
        box = norm(bbox)
        if box is None:
            continue
        name = (getattr(layer, "name", "") or "").lower()
        if getattr(layer, "kind", "") == "pic" and "image" not in boxes:
            boxes["image"] = box
        elif "logo" in name and "logo" not in boxes:
            boxes["logo"] = box
        elif getattr(layer, "placeholder", None) and layer.placeholder.get("type") in ("title", "ctrTitle"):
            boxes["title"] = box
        elif any(token in name for token in ("band", "wave", "decor", "shape")) and "decoration" not in boxes:
            boxes["decoration"] = box
    return boxes


# --------------------------------------------------------------------------- #
# deck-level comparison
# --------------------------------------------------------------------------- #
def visual_regression(reference_dir: Path, candidate_dir: Path, *, threshold_ssim: float = 0.995,
                      threshold_mae: float = 0.005, threshold_mismatch: float = 0.01,
                      diff_dir: Path | None = None,
                      regions: Mapping[str, tuple[float, float, float, float]] | None = None) -> VisualReport:
    refs = sorted(reference_dir.glob("slide-*.png")); cands = sorted(candidate_dir.glob("slide-*.png"))
    pages: list[PageMetrics] = []
    region_metrics: list[RegionMetrics] = []
    for i, (ref, cand) in enumerate(zip(refs, cands), start=1):
        diff_path = diff_dir / f"slide-{i}.png" if diff_dir else None
        mae, mismatch, ssim, passed = compare_images(ref, cand, threshold_ssim=threshold_ssim,
            threshold_mae=threshold_mae, threshold_mismatch=threshold_mismatch, diff_output=diff_path)
        gray_ref = _to_gray_array(ref)
        gray_cand = _to_gray_array(cand, (gray_ref.shape[1], gray_ref.shape[0]))
        edge = edge_diff(gray_ref, gray_cand)
        from PIL import Image
        with Image.open(ref) as ref_im, Image.open(cand) as cand_im:
            width, height = ref_im.size
            candidate_width, candidate_height = cand_im.size
        dimension_match = (width, height) == (candidate_width, candidate_height)
        pages.append(PageMetrics(i, str(ref), str(cand), width, height, mae, mismatch, ssim, passed,
                                 str(diff_path) if diff_path else None, candidate_width, candidate_height,
                                 dimension_match, edge))
        if regions is not False and (regions is not None or i == 1):
            region_metrics.extend(compare_page_regions(ref, cand, regions=regions))

    passed = len(refs) == len(cands) and all(page.passed for page in pages)
    page_scores = [page_score_of(page) for page in pages]
    page_score = round(sum(page_scores) / len(page_scores), 4) if page_scores else 1.0
    critical_scores = [region.score for region in region_metrics if region.critical]
    critical_region_score = round(min(critical_scores), 4) if critical_scores else 1.0
    critical_gate_passed = all(region.passed for region in region_metrics if region.critical)
    status = "visual_pass" if (passed and critical_gate_passed) else "visual_fail"
    return VisualReport(passed and critical_gate_passed, len(refs), len(cands), threshold_ssim,
                        threshold_mae, threshold_mismatch, pages, status, page_score,
                        critical_region_score, region_metrics, critical_gate_passed)


def page_score_of(page: PageMetrics) -> float:
    """Deterministic whole-page score in [0, 1]."""
    return region_score(page.mae, page.mismatch_ratio, page.ssim)


def render_and_compare(reference_pptx: Path, candidate_pptx: Path, workspace: Path,
                       **thresholds: Any) -> VisualReport:
    regions = thresholds.pop("regions", None)
    render_pptx(reference_pptx, workspace / "reference")
    render_pptx(candidate_pptx, workspace / "candidate")
    kwargs = {
        "threshold_ssim": 0.995,
        "threshold_mae": 0.005,
        "threshold_mismatch": 0.01,
    }
    kwargs.update(thresholds)
    return visual_regression(workspace / "reference", workspace / "candidate", diff_dir=workspace / "diff", regions=regions, **kwargs)


def visual_status(reference_pptx: Path, candidate_pptx: Path, workspace: Path, **thresholds: Any) -> dict[str, Any]:
    """Render + compare with explicit status; never downgrades to a pass."""
    try:
        report = render_and_compare(reference_pptx, candidate_pptx, workspace, **thresholds)
    except VisualGateUnavailable as exc:
        return {"status": "renderer_unavailable", "passed": False, "error": str(exc)}
    except RuntimeError as exc:
        return {"status": "renderer_error", "passed": False, "error": str(exc)}
    return {"status": report.status, "passed": report.passed, "report": report.to_dict()}


def write_report(report: VisualReport, output: Path) -> None:
    from .textio import write_json_lf

    write_json_lf(output, report.to_dict())


__all__ = [
    "CRITICAL_REGIONS",
    "CRITICAL_THRESHOLDS",
    "DEFAULT_REGIONS",
    "PageMetrics",
    "RegionMetrics",
    "VisualGateUnavailable",
    "VisualReport",
    "compare_images",
    "compare_page_regions",
    "edge_diff",
    "flatten_pixels",
    "office_binary",
    "page_score_of",
    "preview_backend",
    "rasteriser_available",
    "rasteriser_tools",
    "region_score",
    "regions_from_fidelity",
    "render_and_compare",
    "render_pptx",
    "visual_regression",
    "visual_status",
    "write_report",
]
