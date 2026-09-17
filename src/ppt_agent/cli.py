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
    ir_pptx = sub.add_parser("ir-to-pptx", help="Render Universal IR JSON into an editable PPTX")
    ir_pptx.add_argument("source", type=Path); ir_pptx.add_argument("-o", "--output", required=True, type=Path)
    ir_html = sub.add_parser("ir-to-html", help="Render Universal IR JSON into a self-contained HTML deck")
    ir_html.add_argument("source", type=Path); ir_html.add_argument("-o", "--output", required=True, type=Path)
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

    # --- V1.0 additions ---------------------------------------------------
    build = sub.add_parser("build", help="Plan, build and gate a deck end to end")
    build.add_argument("source", type=Path, nargs="?", help="Markdown source; omit when using --ir")
    build.add_argument("--ir", type=Path, help="Build from an existing IR JSON instead of Markdown")
    build.add_argument("-o", "--out-dir", required=True, type=Path)
    build.add_argument("--stem", default="presentation", help="Base filename for the artifacts")
    build.add_argument("--title"); build.add_argument("--audience"); build.add_argument("--objective")
    build.add_argument("--renderer", help="Renderer name: native-pptx (default) or html")
    build.add_argument("--template", type=Path, help="Reference .pptx whose colours and fonts seed the design theme")
    build.add_argument("--reference", type=Path, help="Reference deck for visual regression")
    build.add_argument("--no-gate", action="store_true", help="Skip the delivery gate")
    build.add_argument("--no-html", action="store_true", help="Skip the HTML preview")
    build.add_argument("--facts", type=Path, help="Fact JSON (array of {claim, source_id, locator}) for the fact lock")
    build.add_argument("--preview", action="store_true", help="Also rasterise the deck to PNG page previews")
    build.add_argument("--preview-dpi", type=float, default=96.0, help="Preview resolution (default 96)")

    caps = sub.add_parser("capabilities", help="Print the contract, host capabilities and renderer inventory")
    caps.add_argument("--host", help="Host profile: codex, workbuddy, doubao, claude, chatgpt")
    caps.add_argument("--json", action="store_true", help="Emit raw JSON instead of a summary")

    audit = sub.add_parser("audit-facts", help="Check every IR claim against a fact registry")
    audit.add_argument("source", type=Path, help="IR JSON to audit")
    audit.add_argument("--facts", required=True, type=Path, help="Fact JSON (array of {claim, source_id, locator})")
    audit.add_argument("-o", "--output", type=Path)

    bench = sub.add_parser("benchmark", help="Run the reproducible benchmark suite over a cases directory")
    bench.add_argument("cases", type=Path, nargs="?", default=Path("benchmarks/cases"))
    bench.add_argument("-o", "--output", required=True, type=Path, help="Benchmark report JSON")
    bench.add_argument("--workspace", type=Path, help="Where to write intermediate runs")

    preview = sub.add_parser("preview", help="Rasterise a rendered PPTX into one PNG per slide")
    preview.add_argument("source", type=Path, help="Path to a .pptx file")
    preview.add_argument("-o", "--output-dir", type=Path, help="Directory for the PNGs (default: <stem>-preview)")
    preview.add_argument("--dpi", type=float, default=96.0, help="Rasterisation resolution (default 96)")

    mcp = sub.add_parser("mcp", help="Run the MCP stdio server (alias of ppt-agent-mcp)")
    mcp.add_argument("--workspace", type=Path, default=None)
    mcp.add_argument("--host", default=None)

    release = sub.add_parser("release-manifest", help="Write a deterministic release manifest")
    release.add_argument("--root", type=Path, default=Path.cwd())
    release.add_argument("-o", "--output", type=Path, default=Path("dist/release-manifest.json"))

    verify = sub.add_parser("release-verify", help="Verify the working tree against a release manifest")
    verify.add_argument("--root", type=Path, default=Path.cwd())
    verify.add_argument("--manifest", type=Path, default=Path("dist/release-manifest.json"))

    # --- V1.11 fidelity engine --------------------------------------------
    fidelity = sub.add_parser("fidelity", help="OOXML fidelity engine (extract/diff/audit/repair/validate)")
    fidelity_sub = fidelity.add_subparsers(dest="fidelity_command", required=True)
    f_extract = fidelity_sub.add_parser("extract", help="Extract the hardened fidelity DNA of one slide")
    f_extract.add_argument("source", type=Path)
    f_extract.add_argument("--slide", type=int, default=1)
    f_extract.add_argument("-o", "--output", required=True, type=Path)
    f_diff = fidelity_sub.add_parser("diff", help="Structurally compare one slide of two decks")
    f_diff.add_argument("reference", type=Path); f_diff.add_argument("candidate", type=Path)
    f_diff.add_argument("--slide", type=int, default=1)
    f_diff.add_argument("--tolerance", type=float, default=0.0005)
    f_diff.add_argument("-o", "--output", type=Path)
    f_audit = fidelity_sub.add_parser("audit", help="Deck-level structural fidelity gate")
    f_audit.add_argument("reference", type=Path); f_audit.add_argument("candidate", type=Path)
    f_audit.add_argument("--tolerance", type=float, default=0.0005)
    f_audit.add_argument("-o", "--output", type=Path)
    f_repair = fidelity_sub.add_parser("repair", help="Iteratively repair a candidate deck against a reference")
    f_repair.add_argument("reference", type=Path); f_repair.add_argument("candidate", type=Path)
    f_repair.add_argument("-o", "--output", required=True, type=Path)
    f_repair.add_argument("--max-iterations", type=int, default=3)
    f_repair.add_argument("--workspace", type=Path)
    f_repair.add_argument("--render", action="store_true", help="Also run the visual gate once the structure matches")
    f_validate = fidelity_sub.add_parser("validate", help="Structural + rendered fidelity validation")
    f_validate.add_argument("reference", type=Path); f_validate.add_argument("candidate", type=Path)
    f_validate.add_argument("--workspace", type=Path)
    f_validate.add_argument("-o", "--output", type=Path)
    f_validate.add_argument("--no-render", action="store_true", help="Skip the rendered comparison")
    f_validate.add_argument("--ssim", type=float, default=0.995)
    f_validate.add_argument("--mae", type=float, default=0.005)
    f_validate.add_argument("--mismatch", type=float, default=0.01)
    return parser


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON: {exc}") from exc


def _write_json(path: Path, payload: object) -> None:
    from .textio import write_json_lf

    write_json_lf(path, payload)


def _agent(host: str | None = None):
    from .adapters import create_adapter
    from .sdk import PptAgent

    return PptAgent(create_adapter(host) if host else None)


def _print_capabilities(payload: dict) -> None:
    print(f"core API      : {payload['core_api_version']}")
    print(f"IR schema     : {payload['ir_schema_version']} (supported: {', '.join(payload['supported_ir_versions'])})")
    adapter = payload["adapter"]
    print(f"adapter       : {adapter['display_name']} [{adapter['name']}]")
    print(f"  declared    : {', '.join(adapter['declared']) or '-'}")
    print(f"  effective   : {', '.join(adapter['effective']) or '-'}")
    negotiation = payload["negotiation"]
    print(f"  negotiation : {'ok' if negotiation['ok'] else 'blocked'}")
    for note in negotiation["notes"]:
        print(f"    - {note}")
    print("renderers     :")
    for renderer in payload["renderers"]:
        state = "ready" if renderer["available"] else "unavailable"
        print(f"  - {renderer['name']} ({state}, editable={renderer['editable']})")
    print("host profiles : " + ", ".join(profile["name"] for profile in payload["host_profiles"]))


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
    if args.command == "ir-to-pptx":
        from .ir import Presentation
        from .renderer import render_presentation
        presentation = Presentation.from_dict(_read_json(args.source))
        output = render_presentation(presentation, args.output)
        print(f"wrote {output} ({len(presentation.slides)} slides)"); return 0
    if args.command == "ir-to-html":
        from .renderers import render_html_deck
        from .ir import Presentation
        presentation = Presentation.from_dict(_read_json(args.source))
        output, warnings = render_html_deck(presentation, args.output)
        for warning in warnings:
            print(f"warning: {warning}")
        print(f"wrote {output} ({len(presentation.slides)} slides)"); return 0
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
    if args.command == "capabilities":
        payload = _agent(args.host).capabilities()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _print_capabilities(payload)
        return 0
    if args.command == "audit-facts":
        agent = _agent()
        presentation = agent.load_ir(args.source)
        facts = json.loads(args.facts.read_text(encoding="utf-8"))
        report = agent.audit_facts(presentation, facts)
        if args.output:
            _write_json(args.output, report)
        for finding in report["findings"]:
            if not finding["supported"]:
                print(f"unsupported: slide={finding['slide']} component={finding['component']} claim={finding['claim'][:80]}")
        print(f"fact lock: {'PASS' if report['passed'] else 'FAIL'} ({report['supported']}/{report['checked']} claims supported)")
        return 0 if report["passed"] else 2
    if args.command == "build":
        agent = _agent()
        facts = json.loads(args.facts.read_text(encoding="utf-8")) if args.facts else None
        outcome = agent.build(
            out_dir=args.out_dir,
            markdown=None if args.ir else args.source.read_text(encoding="utf-8"),
            presentation=agent.load_ir(args.ir) if args.ir else None,
            title=args.title, audience=args.audience, objective=args.objective,
            renderer=args.renderer, template=args.template, reference=args.reference,
            gate=not args.no_gate, emit_html=not args.no_html,
            facts=facts, stem=args.stem,
        )
        for warning in outcome.warnings:
            print(f"warning: {warning}")
        print(f"ir    : {outcome.ir_path}")
        print(f"pptx  : {outcome.pptx_path} (renderer={outcome.renderer})")
        if outcome.html_path:
            print(f"html  : {outcome.html_path}")
        if outcome.gate:
            print(f"gate  : {'PASS' if outcome.gate['passed'] else 'FAIL'} (mode={outcome.gate['mode']}, degraded={outcome.gate['degraded'] or 'none'})")
        if outcome.fact_audit:
            print(f"facts : {'PASS' if outcome.fact_audit['passed'] else 'FAIL'} ({outcome.fact_audit['supported']}/{outcome.fact_audit['checked']} supported)")
        _write_json(Path(args.out_dir) / f"{args.stem}-build.json", outcome.to_dict())
        if args.preview:
            from .preview import rasterize_pptx
            pages = rasterize_pptx(outcome.pptx_path, Path(args.out_dir) / f"{args.stem}-preview", dpi=args.preview_dpi)
            print(f"preview: {len(pages)} page(s) -> {pages[0].parent}" if pages else "preview: no pages")
        print(f"build : {'PASS' if outcome.ok else 'FAIL'} — {outcome.slide_count} slides")
        return 0 if outcome.ok else 2
    if args.command == "benchmark":
        from .benchmark import run_benchmark, summarize, write_report
        workspace = args.workspace or args.output.parent / "benchmark-workspace"
        report = run_benchmark(args.cases, workspace)
        write_report(report, args.output)
        print(summarize(report))
        print(f"wrote {args.output}")
        return 0 if report.passed else 2
    if args.command == "preview":
        from .preview import rasterize_pptx
        pages = rasterize_pptx(args.source, args.output_dir, dpi=args.dpi)
        for page in pages:
            print(page)
        print(f"preview: {len(pages)} page(s)")
        return 0
    if args.command == "mcp":
        from .mcp.server import serve
        return serve(workspace=args.workspace, host=args.host)
    if args.command == "release-manifest":
        from .release import build_manifest, check_versions, write_manifest
        errors = check_versions(args.root)
        for error in errors:
            print(f"version error: {error}")
        if errors:
            return 2
        manifest = build_manifest(args.root)
        target = write_manifest(manifest, args.output)
        print(f"wrote {target} ({manifest['file_count']} files, digest {manifest['digest'][:16]})")
        return 0
    if args.command == "release-verify":
        from .release import read_manifest, verify_manifest
        report = verify_manifest(args.root, read_manifest(args.manifest))
        for name in report["missing"]:
            print(f"missing: {name}")
        for name in report["changed"]:
            print(f"changed: {name}")
        for name in report["extra"]:
            print(f"unexpected: {name}")
        print(f"release verification: {'PASS' if report['ok'] else 'FAIL'} ({report['counts']})")
        return 0 if report["ok"] else 2
    if args.command == "fidelity":
        from .fidelity import extract_fidelity_dna
        from .fidelity_diff import compare_dna
        from .fidelity_gate import compare_decks

        if args.fidelity_command == "extract":
            dna = extract_fidelity_dna(args.source, slide_index=args.slide)
            _write_json(args.output, dna)
            print(f"wrote {args.output} (slide {args.slide}, kind={dna['page_kind']}, "
                  f"layers={len(dna['slide']['shapes'])})")
            return 0
        if args.fidelity_command == "diff":
            report = compare_dna(
                extract_fidelity_dna(args.reference, slide_index=args.slide),
                extract_fidelity_dna(args.candidate, slide_index=args.slide),
                tolerance=args.tolerance,
            )
            payload = report.to_dict()
            payload["reference"] = str(args.reference)
            payload["candidate"] = str(args.candidate)
            payload["slide_index"] = args.slide
            if args.output:
                _write_json(args.output, payload)
            print(f"slide {args.slide}: {'PASS' if report.passed else 'FAIL'} "
                  f"(score={report.score}, issues={report.issue_count})")
            for issue in report.issues[:10]:
                print(f"  {issue.code or issue.category}: {issue.path}")
            return 0 if report.passed else 2
        if args.fidelity_command == "audit":
            gate = compare_decks(args.reference, args.candidate, tolerance=args.tolerance)
            if args.output:
                _write_json(args.output, gate)
            for page in gate["pages"]:
                status = "PASS" if page["passed"] else f"FAIL ({page['issue_count']})"
                print(f"slide {page['slide_index']}: {status}")
            print(f"deck fidelity gate: {'PASS' if gate['passed'] else 'FAIL'}")
            return 0 if gate["passed"] else 2
        if args.fidelity_command == "repair":
            from .fidelity_pipeline import FidelityRepairExhausted, repair_deck
            workspace = args.workspace or args.output.parent / "fidelity-repair"
            try:
                result = repair_deck(
                    args.reference, args.candidate, workspace,
                    max_iterations=args.max_iterations, render=args.render,
                )
            except FidelityRepairExhausted as exc:
                result = exc.payload
            _write_json(args.output, result)
            print(f"iterations: {result['iterations']}")
            print(f"structural: {'PASS' if (result['structural'] or {}).get('passed') else 'FAIL'}")
            if result.get("visual"):
                print(f"visual: {result['visual'].get('status')}")
            for remaining in result.get("remaining_issues", [])[:10]:
                print(f"remaining: {remaining.get('path', remaining)}")
            print(f"repair loop: {'PASS' if result['passed'] else 'FAIL'} -> {result['candidate_final']}")
            return 0 if result["passed"] else 2
        if args.fidelity_command == "validate":
            from .fidelity_pipeline import validate_deck_fidelity
            workspace = args.workspace or (args.output.parent if args.output else Path.cwd()) / "fidelity-validate"
            result = validate_deck_fidelity(
                args.reference, args.candidate, workspace,
                render=not args.no_render,
                threshold_ssim=args.ssim, threshold_mae=args.mae, threshold_mismatch=args.mismatch,
            )
            if args.output:
                _write_json(args.output, result)
            structural = result["structural"]
            print("Fidelity Validation")
            print("-------------------")
            print(f"Structural: {'PASS' if structural['passed'] else 'FAIL'}")
            visual = result["visual"]
            print(f"Visual:     {'SKIP' if visual.get('status') == 'skipped' else visual.get('status', '').upper()}")
            print(f"Slides: {structural['presentation']['reference_slide_count']}")
            if not structural["passed"]:
                for page in structural["pages"]:
                    for issue in page.get("issues", [])[:3]:
                        print(f"  slide {page['slide_index']}: {issue.get('code', issue.get('category', '?'))} {issue.get('path', '')}")
            print(f"validation: {'PASS' if result['passed'] else 'FAIL'}")
            return 0 if result["passed"] else 2
        return 0
    parser.print_help(); return 0


if __name__ == "__main__":
    raise SystemExit(main())
