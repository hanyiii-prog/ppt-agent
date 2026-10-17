"""Contact-sheet composer for deck-level visual rhythm review."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont


def _page_number(image: Path, fallback: int) -> int:
    match = re.search(r"(?:slide|page)[-_ ]*(\d+)", image.stem, re.IGNORECASE)
    return int(match.group(1)) if match else fallback


def build_contact_sheet(
    rendered_pages: Sequence[Path],
    output: Path,
    *,
    cols: int = 4,
    tile_width: int = 320,
    label: bool = True,
) -> Path:
    """Compose rendered page thumbnails into a labeled grid image.

    Returns the output path. Raises ``ValueError`` when ``rendered_pages``
    is empty; callers should treat that as "no contact sheet" rather than
    silently emitting a blank.
    """
    if not rendered_pages:
        raise ValueError("no rendered pages to compose")
    cols = max(1, int(cols))
    rows = (len(rendered_pages) + cols - 1) // cols
    # Determine a consistent tile height from the first image aspect ratio.
    with Image.open(rendered_pages[0]) as probe:
        ratio = probe.height / probe.width
    tile_height = max(64, int(round(tile_width * ratio)))
    label_h = 22 if label else 0
    gap = 4
    sheet_w = cols * tile_width + (cols + 1) * gap
    sheet_h = rows * (tile_height + label_h) + (rows + 1) * gap
    sheet = Image.new("RGB", (sheet_w, sheet_h), (240, 240, 240))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=14)
    except TypeError:
        font = ImageFont.load_default()
    for index, page_path in enumerate(rendered_pages):
        row, col = divmod(index, cols)
        x = gap + col * (tile_width + gap)
        y = gap + row * (tile_height + label_h + gap)
        with Image.open(page_path) as source:
            thumb = source.convert("RGB")
            thumb.thumbnail((tile_width, tile_height), Image.Resampling.LANCZOS)
            sheet.paste(thumb, (x, y))
        if label:
            page_no = _page_number(Path(page_path), index + 1)
            draw.text((x + 4, y + tile_height + 2), f"p{page_no}", fill=(40, 40, 40), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, format="JPEG", quality=85)
    return output
