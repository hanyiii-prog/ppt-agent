from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .markdown import parse_markdown
from .qa import validate_ir
from .template import analyze_pptx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ppt-agent",
        description="Portable agent-native presentation engineering framework",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    validate = sub.add_parser("validate-ir", help="Validate basic IR structure")
    validate.add_argument("path", type=Path)

    qa = sub.add_parser("qa-ir", help="Run IR quality gates")
    qa.add_argument("path", type=Path)

    markdown = sub.add_parser("markdown-to-ir", help="Convert Markdown to Universal IR")
    markdown.add_argument("source", type=Path)
    markdown.add_argument("-o", "--output", required=True, type=Path)

    template = sub.add_parser("analyze-pptx", help="Extract Template DNA from a PPTX")
    template.add_argument("source", type=Path)
    template.add_argument("-o", "--output", required=True, type=Path)
    return parser


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON: {exc}") from exc


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command in {"validate-ir", "qa-ir"}:
        report = validate_ir(_read_json(args.path))
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.passed else 2

    if args.command == "markdown-to-ir":
        presentation = parse_markdown(
            args.source.read_text(encoding="utf-8"), source_id=args.source.name
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(presentation.to_json() + "\n", encoding="utf-8")
        print(f"wrote {args.output} ({len(presentation.slides)} slides)")
        return 0

    if args.command == "analyze-pptx":
        result = analyze_pptx(args.source)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.output} ({result['slide_count']} slides)")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
