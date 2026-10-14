from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .dna_to_ir import template_dna_to_ir
from .ir import Presentation



def load_template_dna(path: str | Path) -> dict[str, Any]:
    """Load a Template DNA JSON document."""
    return json.loads(Path(path).read_text(encoding="utf-8"))



def template_dna_file_to_ir(path: str | Path) -> Presentation:
    """Convert a Template DNA JSON file into Universal Presentation IR."""
    dna = load_template_dna(path)
    return template_dna_to_ir(dna, source=str(path))



def template_dna_file_to_ir_json(path: str | Path, *, indent: int = 2) -> str:
    """Convert a Template DNA JSON file and serialize the IR result."""
    return template_dna_file_to_ir(path).to_json(indent=indent)
