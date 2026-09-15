from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .dna_to_ir import template_dna_to_ir
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
    dna_ir = sub.add_parser("dna-to-ir", help="Convert Template DNA JSON to Universal IR")
    dna_ir.add_argument("source", type=Path); dna_ir.add_argument("-o", "--output", required=True, type=Path)
    convert = sub.add_parser("pptx-to-ir", help="Analyze a PPTX and convert its Template DNA to Universal IR")
    convert.add_argument("source", type=Path); convert.add_argument("-o", "--output", required=True, type=Path)
    render = sub.add_parser("render-pptx", help="Render every PPTX slide to PNG")
    render.add_argument("source", type=Path); render.add_argument("-o", "--output", required=True, type=Path)
    visual = sub.add_parser("visual-regression", help="Render two decks and compare every page")
    visual.add_argument("reference", type=Path); visual.add_argument("candidate", type=Path)
    visual.add_argument("-o", "--output", required=True, type=Path); visual.add_argument("--workspace", type=Path)
    visual.add_argument("--ssim", type=float, default=0.995); visual.add_argument("--mae", type=float, default=0.005)
    visual.add_argument("--mismatch", type=float, default=0.01)
    gate = sub.add_parser("validate-pptx", help="Run the complete per-page production quality gate")
    gate.add_argument("source", type=Path); gate.add_argument("-o", "--output", required=True, type=Path)
    gate.add_argument("--workspace", type=Path); gate.add_argument("--reference", type=Path)
    gate.add_argument("--ssim", type=float, default=0.995); gate.add_argument("--mae", type=float, default=0.005)
    gate.add_argument("--mismatch", type=float, default=0.01)
    return parser


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON: {exc}") from exc


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = build_parser(); args = parser.parse_args()
    if args.command in {"validate-ir", "qa-ir"}:
        report = validate_ir(_read_json(args.path)); print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2)); return 0 if report.passed else 2
    if args.command == "markdown-to-ir":
        presentation = parse_markdown(args.source.read_text(encoding="utf-8"), source_id=args.source.name)
        _write_json(args.output, json.loads(presentation.to_json())); print(f"wrote {args.output} ({len(presentation.slides)} slides)"); return 0
    if args.command == "analyze-pptx":
        result = analyze_pptx(args.source); _write_json(args.output, result)
        print(f"wrote {args.output} ({result['presentation']['slide_count']} slides)"); return 0
    if args.command == "dna-to-ir":
        dna = _read_json(args.source); presentation = template_dna_to_ir(dna, source=args.source.name)
        _write_json(args.output, json.loads(presentation.to_json())); print(f"wrote {args.output} ({len(presentation.slides)} slides)"); return 0
    if args.command == "pptx-to-ir":
        dna = analyze_pptx(args.source); presentation = template_dna_to_ir(dna, source=args.source.name)
        _write_json(args.output, json.loads(presentation.to_json())); print(f"wrote {args.output} ({len(presentation.slides)} slides)"); return 0
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
        from .delivery import DeliveryPolicy, validate_delivery
        workspace = args.workspace or args.output.parent / "production-qa"
        policy = DeliveryPolicy(visual_ssim=args.ssim, visual_mae=args.mae, visual_mismatch=args.mismatch)
        page_gate, critic_gate, visual_gate = validate_delivery(args.source, workspace, reference_pptx=args.reference, policy=policy)
        result = {
            "passed": page_gate.passed and critic_gate.passed and (visual_gate is None or visual_gate.passed),
            "page_gate": page_gate.to_dict(),
            "critic_gate": critic_gate.to_dict(),
            "visual_gate": visual_gate.to_dict() if visual_gate else None,
        }
        _write_json(args.output, result)
        for page in page_gate.pages:
            print(f"page {page.page}: shapes={page.shape_count} oob={page.out_of_bounds} blank={page.blank_ratio:.3%} {'PASS' if page.passed else 'FAIL'}")
        for finding in critic_gate.pages:
            print(f"page {finding.page}: critic {finding.severity}/{finding.rule} {finding.message}")
        if visual_gate:
            for page in visual_gate.pages:
                print(f"page {page.page}: SSIM={page.ssim:.5f} MAE={page.mae:.5f} mismatch={page.mismatch_ratio:.3%} {'PASS' if page.passed else 'FAIL'}")
        print(f"production delivery gate: {'PASS' if result['passed'] else 'FAIL'}"); return 0 if result["passed"] else 2
    parser.print_help(); return 0


if __name__ == "__main__":
    raise SystemExit(main())
