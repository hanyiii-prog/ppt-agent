"""Real rasterisation backends: PowerPoint and LibreOffice.

Why this module exists
----------------------
The Pillow preview (``preview.rasterize_pptx``) is a *hand-painted approximation*
of PowerPoint. It cannot reproduce master backgrounds, full-bleed images, or
picture crops (``srcRect``), so anything judged from its output is unreliable:
a cover that really renders as a full-width building photo over a gradient can
come back looking like black text on a half-width image. Every automated visual
check that is supposed to represent "what the user actually sees" must therefore
render with the real engine, not the approximation.

Two real backends are supported, in fidelity order:

``powerpoint``   native PowerPoint via COM (Windows; the ground truth)
``libreoffice``  soffice headless -> PDF -> pdftoppm

The PowerPoint route shells out to ``powershell.exe`` driving the
``PowerPoint.Application`` COM server directly. That deliberately avoids a hard
dependency on pywin32/comtypes (neither is installed here) and reuses a code
path already proven on this machine. Slides are opened read-only and
windowless. The source deck is copied to an ASCII path first, because PowerPoint
and the COM ``Open`` call are unreliable with non-ASCII filenames and the
"protected view" that follows files marked from the internet.

Nothing in this module silently falls back to the Pillow approximation: a real
backend either renders or raises.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence
import platform

EMU_PER_INCH = 914400
_POWERSHELL = "powershell.exe"

# PowerPoint COM ProgID is registered machine-wide when the desktop app is
# installed; its presence is a cheaper and more reliable probe than locating
# POWERPNT.EXE, which can live in per-user / Click-to-Run / WindowsApps paths.
_POWERPOINT_PROGID = "PowerPoint.Application"


def powerpoint_available() -> bool:
    """True when the PowerPoint COM server is registered on this host."""
    # COM is Windows-only. winreg is imported lazily (never at module scope) so
    # the package stays importable on the Linux CI runners.
    if platform.system() != "Windows" or not shutil.which(_POWERSHELL):
        return False
    import winreg  # noqa: PLC0415 - guarded by the Windows check above

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, _POWERPOINT_PROGID):
            return True
    except OSError:
        return False


def _slide_pixel_size(pptx: Path, dpi: float) -> tuple[int, int]:
    """Pixel export size for ``pptx`` at ``dpi``, preserving the aspect ratio."""
    from pptx import Presentation
    from pptx.util import Emu

    deck = Presentation(str(pptx))
    width_in = Emu(int(deck.slide_width)).inches
    height_in = Emu(int(deck.slide_height)).inches
    width_px = max(int(round(width_in * dpi)), 64)
    height_px = max(int(round(height_in * dpi)), 64)
    return width_px, height_px


_EXPORT_PS = r"""
$ErrorActionPreference = 'Stop'
$src = $env:PP_SRC
$out = $env:PP_OUT
$w = [int]$env:PP_W
$h = [int]$env:PP_H
New-Item -ItemType Directory -Force -Path $out | Out-Null
$app = New-Object -ComObject PowerPoint.Application
try {
    $pres = $app.Presentations.Open($src, $true, $false, $false)
    $index = 0
    foreach ($slide in $pres.Slides) {
        $index += 1
        $target = Join-Path $out ('slide-{0:D4}.png' -f $index)
        $slide.Export($target, 'PNG', $w, $h)
    }
    $pres.Close()
    Write-Output $index
} finally {
    $app.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
"""


def _ascii_copy(src: Path, staging: Path) -> Path:
    """Copy ``src`` into an ASCII-only staging dir to dodge COM path issues."""
    staging.mkdir(parents=True, exist_ok=True)
    target = staging / "deck.pptx"
    shutil.copyfile(src, target)
    return target


def rasterize_with_powerpoint(
    pptx: str | Path,
    output_dir: str | Path,
    *,
    dpi: float = 144.0,
    prefix: str = "slide",
    timeout: float = 240.0,
) -> list[Path]:
    """Export every slide of ``pptx`` to a PNG using real PowerPoint.

    Raises :class:`RuntimeError` when PowerPoint is missing or the export
    fails; it never returns a partial or approximate render.
    """
    if not powerpoint_available():
        raise RuntimeError("PowerPoint COM backend is not available on this host")

    source = Path(pptx).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"pptx not found: {source}")
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    width_px, height_px = _slide_pixel_size(source, dpi)

    with tempfile.TemporaryDirectory(prefix="ppt-agent-real-") as tmp:
        staging = Path(tmp) / "staging"
        copied = _ascii_copy(source, staging)
        script = staging / "export.ps1"
        script.write_text(_EXPORT_PS, encoding="utf-8")
        env = {
            "PP_SRC": str(copied),
            "PP_OUT": str(destination),
            "PP_W": str(width_px),
            "PP_H": str(height_px),
        }
        completed = subprocess.run(  # noqa: S603 - fixed interpreter, args in env
            [_POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
             "Bypass", "-File", str(script)],
            capture_output=True, timeout=timeout, env={**_shell_env(), **env},
        )
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace")[-2000:]
            raise RuntimeError(
                f"PowerPoint export failed (rc={completed.returncode}): {detail}"
            )

    pages = sorted(destination.glob(f"{prefix}-*.png"))
    if not pages:
        raise RuntimeError(f"PowerPoint produced no PNGs for {source}")
    return pages


def _shell_env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    env.setdefault("SystemRoot", r"C:\Windows")
    return env


def real_backend() -> str | None:
    """Highest-fidelity real rasteriser usable on this host, or None.

    Order is fidelity, not convenience: native PowerPoint is the ground truth
    the user sees; LibreOffice is a portable real engine; Pillow is *not* real
    and is therefore never returned here.
    """
    if powerpoint_available():
        return "powerpoint"
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice and shutil.which("pdftoppm"):
        return "libreoffice"
    return None


def render_real(
    pptx: str | Path,
    output_dir: str | Path,
    *,
    dpi: int = 144,
    backend: str | None = None,
) -> list[Path]:
    """Render with a real engine (PowerPoint/LibreOffice); raises on failure."""
    backend = backend or real_backend()
    if backend == "powerpoint":
        return rasterize_with_powerpoint(pptx, output_dir, dpi=float(dpi))
    if backend == "libreoffice":
        return _render_libreoffice(Path(pptx), Path(output_dir), dpi=int(dpi))
    raise RuntimeError("no real rasterisation backend available (PowerPoint or LibreOffice)")


def _render_libreoffice(pptx: Path, output_dir: Path, *, dpi: int) -> list[Path]:
    binary = shutil.which("soffice") or shutil.which("libreoffice")
    if not binary:
        raise RuntimeError("LibreOffice (soffice) not found")
    if not shutil.which("pdftoppm"):
        raise RuntimeError("pdftoppm not found (install poppler-utils)")
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ppt-agent-render-") as tmp:
        tmp_path = Path(tmp)
        subprocess.run(  # noqa: S603
            [binary, "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(pptx)],
            check=True, capture_output=True,
        )
        pdf = tmp_path / f"{pptx.stem}.pdf"
        if not pdf.exists():
            raise RuntimeError(f"LibreOffice did not produce PDF for {pptx}")
        subprocess.run(  # noqa: S603
            ["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(output_dir / "slide")],
            check=True, capture_output=True,
        )
    pages = sorted(output_dir.glob("slide-*.png"))
    if not pages:
        raise RuntimeError(f"no rendered pages found for {pptx}")
    return pages


__all__: Sequence[str] = (
    "powerpoint_available",
    "rasterize_with_powerpoint",
    "real_backend",
    "render_real",
)
