"""Thin CLI entry for the V2.1 end-to-end pipeline.

``python -m ppt_agent.agent.run --source deck.md --out dist/pipeline``
prints the JSON pipeline report (including the honest llm disclosure).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ppt-agent-pipeline",
        description="V2.1 end-to-end pipeline: markdown -> analyzed, planned, solved, gated deck",
    )
    parser.add_argument("--source", required=True, help="path to a Markdown file")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--density", default="standard",
                        choices=["compact", "standard", "air"])
    parser.add_argument("--engine", default="solver", choices=["legacy", "solver"])
    args = parser.parse_args(argv)

    markdown = Path(args.source).read_text(encoding="utf-8")
    report: dict[str, Any] = run_pipeline(
        markdown, out_dir=args.out, density=args.density, engine=args.engine
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
