from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .markdown import parse_markdown
from .qa import validate_ir
from .template import analyze_pptx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ppt-agent", description="Portable agent-native presentation engineering framework")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    validate = sub.add_parser("validate-ir", help="Validate basic IR structure")
    validate.add_argument("path", type=Path)
    qa = sub.add_parser("qa-ir", help="Run IR quality gates")
    qa.add_argument("path", type=Path)
    markdown = sub.add_parser("markdown-to-ir", help="Convert Markdown to Universal IR")
    markdown.add_argument("source", type=Path); markdown.add_argument("-o", "--output", required=True, type=Path)
    template = sub.add_parser("analyze-pptx", help="Extract Template DNA from a PPTX")
    template.add_argument("source", type=Path); template.add_argument("-o", "--output", required=True, type=Path)
    render = sub.add_parser("render-pptx", help="Render every PPTX slide to PNG")
    render.add_argument("source", type=Path); render.add_argument("-o", "--output", required=True, type=Path)
    visual = sub.add_parser("visual-regression", help="Render two decks and compare every page")
    visual.add_argument("reference", type=Path); visual.add_argument("candidate", type=Path)
    visual.add_argument("-o", "--output", required=True, type=Path); visual.add_argument("--workspace", type=Path)
    visual.add_argument("--ssim", type=float, default=0.995); visual.add_argument("--mae", type=float, default=0.005)
    visual.add_argument("--mismatch", type=float, default=0.01)
    gate = sub.add_parser("validate-pptx", help="Render and run per-page production quality gates")
    gate.add_argument("source", type=Path); gate.add_argument("-o", "--output", required=True, type=Path); gate.add_argument("--workspace", type=Path)
    return parser


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON: {exc}") from exc


def main() -> int:
    parser = build_parser(); args = parser.parse_args()
    if args.command in {"validate-ir", "qa-ir"}:
        report = validate_ir(_read_json(args.path)); print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2)); return 0 if report.passed else 2
    if args.command == "markdown-to-ir":
        presentation = parse_markdown(args.source.read_text(encoding="utf-8"), source_id=args.source.name)
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(presentation.to_json() + "\n", encoding="utf-8")
        print(f"wrote {args.output} ({len(presentation.slides)} slides)"); return 0
    if args.command == "analyze-pptx":
        result = analyze_pptx(args.source); args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.output} ({result['slide_count']} slides)"); return 0
    if args.command == "render-pptx":
        from .visual_regression import render_pptx
        pages = render_pptx(args.source, args.output); print(f"rendered {len(pages)} slides to {args.output}"); return 0
    if args.command == "visual-regression":
        from .visual_regression import render_and_compare, write_report
        workspace = args.workspace or args.output.parent / "visual-regression"
        report = render_and_compare(args.reference, args.candidate, workspace, threshold_ssim=args.ssim, threshold_mae=args.mae, threshold_mismatch=args.mismatch)
        write_report(report, args.output)
        for page in report.pages:
            print(f"page {page.page}: SSIM={page.ssim:.5f} MAE={page.mae:.5f} mismatch={page.mismatch_ratio:.3%} {'PASS' if page.passed else 'FAIL'}")
        print(f"visual gate: {'PASS' if report.passed else 'FAIL'}"); return 0 if report.passed else 2
    if args.command == "validate-pptx":
        from .page_validation import validate_rendered_pages
        from .visual_regression import render_pptx
        workspace = args.workspace or args.output.parent / "rendered"
        pages = render_pptx(args.source, workspace); report = validate_rendered_pages(args.source, pages)
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for page in report.pages:
            print(f"page {page.page}: shapes={page.shape_count} oob={page.out_of_bounds} blank={page.blank_ratio:.3%} {'PASS' if page.passed else 'FAIL'}")
        print(f"production page gate: {'PASS' if report.passed else 'FAIL'}"); return 0 if report.passed else 2
    parser.print_help(); return 0


if __name__ == "__main__":
    raise SystemExit(main())
