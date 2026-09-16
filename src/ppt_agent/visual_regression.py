from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageStat
import numpy as np


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


@dataclass
class VisualReport:
    passed: bool
    page_count_reference: int
    page_count_candidate: int
    threshold_ssim: float
    threshold_mae: float
    threshold_mismatch: float
    pages: list[PageMetrics]

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


# LibreOffice ships as `libreoffice` on Debian/Ubuntu and `soffice` on Windows
# and most RPM distributions. Probe both instead of assuming one.
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
    """Which rasterisation backend can actually run here.

    LibreOffice + pdftoppm is preferred because it is a true Office renderer.
    When neither is installed the Pillow backend in ``preview`` keeps visual QA
    alive instead of silently degrading every gate to structural checks.
    """
    if office_binary() is not None and shutil.which("pdftoppm") is not None:
        return "libreoffice"
    try:
        from PIL import Image  # noqa: F401
    except Exception:  # pragma: no cover - depends on the environment
        return None
    return "pillow"


def rasteriser_available() -> bool:
    """True when a deck can actually be rasterised on this host."""
    return preview_backend() is not None


def flatten_pixels(image: "Image.Image") -> list:
    """Read every pixel as a flat sequence.

    `Image.getdata()` is deprecated and disappears in Pillow 14, so prefer the
    replacement when the installed Pillow provides it.
    """
    getter = getattr(image, "get_flattened_data", None)
    if callable(getter):
        return list(getter())
    return list(image.getdata())


def _prepare_output_dir(output_dir: Path) -> None:
    """Remove stale renders so a previous larger deck cannot affect page counts."""
    if output_dir.exists():
        for child in output_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    else:
        output_dir.mkdir(parents=True, exist_ok=True)


def render_pptx(pptx: Path, output_dir: Path, dpi: int = 144) -> list[Path]:
    """Render a PPTX to one PNG per slide, named ``slide-NN.png``.

    Uses LibreOffice + pdftoppm when available, otherwise the deterministic
    Pillow backend so visual gates still run on a bare machine.
    """
    backend = preview_backend()
    if backend is None:
        raise RuntimeError(
            "no rasteriser available: install LibreOffice (soffice + pdftoppm) "
            "or Pillow to enable visual gates"
        )
    _prepare_output_dir(output_dir)

    if backend == "libreoffice":
        binary = office_binary()
        with tempfile.TemporaryDirectory(prefix="ppt-agent-render-") as tmp:
            tmp_path = Path(tmp)
            _run([binary, "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(pptx)])
            pdf = tmp_path / f"{pptx.stem}.pdf"
            if not pdf.exists():
                raise RuntimeError(f"LibreOffice did not produce PDF for {pptx}")
            _run(["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(output_dir / "slide")])
        pages = sorted(output_dir.glob("slide-*.png"))
    else:
        from .preview import rasterize_pptx

        pages = sorted(rasterize_pptx(pptx, output_dir, dpi=float(dpi), prefix="slide"))

    if not pages:
        raise RuntimeError(f"no rendered pages found for {pptx}")
    return pages


def _to_gray_array(path: Path, size: tuple[int, int] | None = None) -> np.ndarray:
    with Image.open(path) as im:
        image = im.convert("L")
        if size and image.size != size:
            image = image.resize(size, Image.Resampling.LANCZOS)
        return np.asarray(image, dtype=np.float32) / 255.0


def _block_ssim(a: np.ndarray, b: np.ndarray, block: int = 8) -> float:
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


def compare_images(reference: Path, candidate: Path, *, threshold_ssim: float = 0.995,
                   threshold_mae: float = 0.005, threshold_mismatch: float = 0.01,
                   diff_output: Path | None = None) -> tuple[float, float, float, bool]:
    with Image.open(reference) as ref_im, Image.open(candidate) as cand_im:
        ref = ref_im.convert("RGB"); cand = cand_im.convert("RGB")
        if ref.size != cand.size:
            cand = cand.resize(ref.size, Image.Resampling.LANCZOS)
        diff = ImageChops.difference(ref, cand)
        mae = sum(ImageStat.Stat(diff).mean) / (3 * 255)
        mismatch = float(np.any(np.asarray(diff, dtype=np.uint8) > 8, axis=2).mean())
    gray_ref = _to_gray_array(reference)
    gray_cand = _to_gray_array(candidate, (gray_ref.shape[1], gray_ref.shape[0]))
    ssim = _block_ssim(gray_ref, gray_cand)
    passed = ssim >= threshold_ssim and mae <= threshold_mae and mismatch <= threshold_mismatch
    if diff_output:
        diff_output.parent.mkdir(parents=True, exist_ok=True)
        diff.point(lambda p: min(255, p * 4)).save(diff_output)
    return mae, mismatch, ssim, passed


def visual_regression(reference_dir: Path, candidate_dir: Path, *, threshold_ssim: float = 0.995,
                      threshold_mae: float = 0.005, threshold_mismatch: float = 0.01,
                      diff_dir: Path | None = None) -> VisualReport:
    refs = sorted(reference_dir.glob("slide-*.png")); cands = sorted(candidate_dir.glob("slide-*.png"))
    pages: list[PageMetrics] = []
    for i, (ref, cand) in enumerate(zip(refs, cands), start=1):
        diff_path = diff_dir / f"slide-{i}.png" if diff_dir else None
        mae, mismatch, ssim, passed = compare_images(ref, cand, threshold_ssim=threshold_ssim,
            threshold_mae=threshold_mae, threshold_mismatch=threshold_mismatch, diff_output=diff_path)
        with Image.open(ref) as im:
            width, height = im.size
        pages.append(PageMetrics(i, str(ref), str(cand), width, height, mae, mismatch, ssim, passed,
                                 str(diff_path) if diff_path else None))
    passed = len(refs) == len(cands) and all(page.passed for page in pages)
    return VisualReport(passed, len(refs), len(cands), threshold_ssim, threshold_mae, threshold_mismatch, pages)


def render_and_compare(reference_pptx: Path, candidate_pptx: Path, workspace: Path, **thresholds: float) -> VisualReport:
    render_pptx(reference_pptx, workspace / "reference")
    render_pptx(candidate_pptx, workspace / "candidate")
    return visual_regression(workspace / "reference", workspace / "candidate", diff_dir=workspace / "diff", **thresholds)


def write_report(report: VisualReport, output: Path) -> None:
    from .textio import write_json_lf

    write_json_lf(output, report.to_dict())
