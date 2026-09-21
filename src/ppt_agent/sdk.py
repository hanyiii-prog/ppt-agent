"""High-level SDK facade.

One stable entry point for host adapters, the CLI and the MCP server. Nothing
here invents presentation logic: every method delegates to the module that owns
that concern, so the CLI and the tool surface cannot drift apart.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from .adapters import HostAdapter, default_adapter, describe_hosts
from .contracts import (
    ADAPTER_PROTOCOL_VERSION,
    CORE_API_VERSION,
    IR_SCHEMA_VERSION,
    contract_descriptor,
)
from .fact_registry import FactRegistry, audit_presentation
from .ir import Presentation
from .markdown import parse_markdown
from .renderers import (
    RenderResult,
    describe_renderers,
    render_with,
    select_renderer,
)
from .story import Story, architect_story, story_to_ir

# Capabilities the pipeline would like; missing ones degrade documented gates.
PIPELINE_REQUIREMENTS: tuple[str, ...] = ("filesystem", "render_preview")


@dataclass
class BuildOutcome:
    """Artifacts and gate results from a full build."""

    ok: bool
    slide_count: int
    ir_path: str | None
    pptx_path: str | None
    html_path: str | None
    renderer: str | None
    gate: dict[str, Any] | None
    manifest: dict[str, Any] | None
    fact_audit: dict[str, Any] | None
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "slide_count": self.slide_count,
            "ir_path": self.ir_path,
            "pptx_path": self.pptx_path,
            "html_path": self.html_path,
            "renderer": self.renderer,
            "gate": self.gate,
            "manifest": self.manifest,
            "fact_audit": self.fact_audit,
            "warnings": list(self.warnings),
        }


class PptAgent:
    """The stable SDK surface.

    Every stage of the pipeline is exposed as one method, and `build()` chains
    them into the loop described in `docs/architecture.md`.
    """

    def __init__(self, adapter: HostAdapter | None = None) -> None:
        self.adapter = adapter or default_adapter()

    # --- introspection ----------------------------------------------------
    def capabilities(self) -> dict[str, Any]:
        descriptor = contract_descriptor()
        negotiation = self.adapter.negotiate(PIPELINE_REQUIREMENTS)
        descriptor.update({
            "core_api_version": CORE_API_VERSION,
            "ir_schema_version": IR_SCHEMA_VERSION,
            "adapter_protocol_version": ADAPTER_PROTOCOL_VERSION,
            "adapter": self.adapter.describe().to_dict(),
            "negotiation": negotiation.to_dict(),
            "renderers": describe_renderers(),
            "host_profiles": describe_hosts(),
        })
        return descriptor

    def require(self, capabilities: Iterable[str]) -> dict[str, Any]:
        return self.adapter.check(capabilities).to_dict()

    # --- planning ---------------------------------------------------------
    def story(
        self,
        markdown: str,
        *,
        title: str | None = None,
        audience: str | None = None,
        objective: str | None = None,
    ) -> Story:
        return architect_story(markdown, title=title, audience=audience, objective=objective)

    def plan(
        self,
        markdown: str,
        *,
        title: str | None = None,
        audience: str | None = None,
        objective: str | None = None,
    ) -> Presentation:
        """Markdown -> narrative outline -> Universal IR."""
        return story_to_ir(self.story(markdown, title=title, audience=audience, objective=objective))

    def parse(self, markdown: str, *, source_id: str = "markdown") -> Presentation:
        """Markdown -> IR using the flat parser (no story inference)."""
        return parse_markdown(markdown, source_id=source_id)

    # --- template intelligence -------------------------------------------
    def analyze_template(self, pptx: str | Path) -> dict[str, Any]:
        from .template import analyze_pptx

        return analyze_pptx(Path(pptx))

    def template_to_ir(self, source: str | Path) -> Presentation:
        from .dna_to_ir import template_dna_to_ir

        path = Path(source)
        if path.suffix.lower() == ".json":
            import json

            return template_dna_to_ir(json.loads(path.read_text(encoding="utf-8")), source=path.name)
        return template_dna_to_ir(self.analyze_template(path), source=path.name)

    # --- clone-shell route --------------------------------------------------
    def clone_plan(self, template: str | Path) -> dict[str, Any]:
        """Inspect a template for the clone route: shells by role plus the
        per-page-kind DNA summary an agent needs to write a page plan."""
        from .clone_build import plan_template

        return plan_template(Path(template))

    def clone_build(
        self,
        template: str | Path,
        pages: list[dict[str, Any]],
        output: str | Path,
        *,
        audit: bool = True,
    ) -> dict[str, Any]:
        """Render a JSON page plan through the clone route (see
        `ppt_agent.clone_build`); returns artifact paths and the page audit."""
        from .clone_build import render_clone_deck

        return render_clone_deck(template, pages, output, audit=audit)

    def clone_audit(self, pptx: str | Path) -> dict[str, Any]:
        """Run the clone-route page audit over a finished deck."""
        from .clone_build import audit_deck

        return audit_deck(Path(pptx))

    # --- IR io ------------------------------------------------------------
    def load_ir(self, path: str | Path) -> Presentation:
        import json

        return Presentation.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save_ir(self, presentation: Presentation, path: str | Path) -> Path:
        from .textio import write_text_lf

        return write_text_lf(path, presentation.to_json() + "\n")

    # --- build ------------------------------------------------------------
    def render(
        self,
        presentation: Presentation,
        output: str | Path,
        *,
        renderer: str | None = None,
        editable: bool | None = None,
    ) -> RenderResult:
        return render_with(presentation, output, renderer=renderer, editable=editable)

    def renderer_for(self, name: str | None = None, *, editable: bool | None = None) -> str:
        return select_renderer(name, editable=editable).name

    # --- quality gates ----------------------------------------------------
    def validate_ir(self, presentation: Presentation | dict[str, Any]) -> dict[str, Any]:
        from .qa import validate_ir as run_ir_qa

        payload = presentation.to_dict() if isinstance(presentation, Presentation) else presentation
        return run_ir_qa(payload).to_dict()

    def gate(
        self,
        pptx: str | Path,
        *,
        workspace: str | Path,
        reference: str | Path | None = None,
        policy: Any = None,
    ) -> dict[str, Any]:
        """Run the delivery gate, degrading to structural checks when needed."""
        from .page_validation import validate_structural_pages

        deck = Path(pptx)
        target = Path(workspace)
        degraded: list[str] = []

        if "render_preview" in self.adapter.effective():
            from .delivery import DeliveryPolicy, validate_delivery

            page_gate, critic_gate, visual_gate = validate_delivery(
                deck,
                target,
                reference_pptx=Path(reference) if reference else None,
                policy=policy or DeliveryPolicy(),
            )
            passed = (
                page_gate.passed
                and critic_gate.passed
                and (visual_gate is None or visual_gate.passed)
            )
            return {
                "passed": passed,
                "mode": "rendered",
                "candidate": str(deck),
                "page_gate": page_gate.to_dict(),
                "critic_gate": critic_gate.to_dict(),
                "visual_gate": visual_gate.to_dict() if visual_gate else None,
                "degraded": degraded,
            }

        degraded.append("render_preview")
        structural = validate_structural_pages(deck)
        # Even without a rasteriser the clone-route layout audit measures the
        # deck structurally, so 质检 keeps teeth: fold it into the page gate.
        try:
            from .delivery import merge_layout_audit, run_layout_audit
            structural = merge_layout_audit(structural, run_layout_audit(deck))
        except Exception:  # pragma: no cover - audit must never crash the gate
            pass
        return {
            "passed": structural.passed,
            "mode": "structural",
            "candidate": str(deck),
            "page_gate": structural.to_dict(),
            "critic_gate": None,
            "visual_gate": None,
            "degraded": degraded,
        }

    def audit_facts(
        self,
        presentation: Presentation,
        facts: Sequence[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        registry = FactRegistry()
        for item in facts or ():
            registry.register(
                str(item.get("claim", "")),
                source_id=str(item.get("source_id", "unspecified")),
                locator=item.get("locator"),
                quote=item.get("quote"),
            )
        report = audit_presentation(presentation, registry)
        unsupported = [entry for entry in report if not entry["supported"]]
        return {
            "checked": len(report),
            "supported": len(report) - len(unsupported),
            "unsupported": len(unsupported),
            "passed": not unsupported,
            "findings": report,
        }

    # --- end to end -------------------------------------------------------
    def build(
        self,
        *,
        out_dir: str | Path,
        markdown: str | None = None,
        presentation: Presentation | None = None,
        title: str | None = None,
        audience: str | None = None,
        objective: str | None = None,
        renderer: str | None = None,
        template: str | Path | None = None,
        reference: str | Path | None = None,
        gate: bool = True,
        emit_html: bool = True,
        facts: Sequence[dict[str, Any]] | None = None,
        stem: str = "presentation",
    ) -> BuildOutcome:
        """Plan -> IR -> build -> gate, returning every artifact path."""
        output_dir = Path(out_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []

        if presentation is None:
            if markdown is None:
                raise ValueError("build() needs either markdown or a Presentation IR")
            presentation = self.plan(
                markdown, title=title, audience=audience, objective=objective
            )
        if template is not None:
            from .theme import theme_from_dna

            dna = self.analyze_template(template)
            resolved = theme_from_dna(dna, name=f"template:{Path(template).stem}")
            presentation.theme = resolved.to_dict()
            warnings.append(
                f"template theme from {Path(template).name}: "
                f"primary #{resolved.primary}, accent #{resolved.accent}, font {resolved.font_title}"
            )

        if not presentation.slides:
            warnings.append("presentation IR contains no slides")

        ir_path = self.save_ir(presentation, output_dir / f"{stem}.json")

        render_result = self.render(presentation, output_dir / f"{stem}.pptx", renderer=renderer)
        warnings.extend(render_result.warnings)

        html_path: str | None = None
        if emit_html:
            html_result = render_with(presentation, output_dir / f"{stem}.html", renderer="html")
            html_path = html_result.path
            warnings.extend(html_result.warnings)

        gate_result = None
        manifest = None
        if gate:
            gate_result = self.gate(
                render_result.path, workspace=output_dir / "qa", reference=reference
            )
            manifest = self._manifest(gate_result, reference=reference)

        fact_audit = self.audit_facts(presentation, facts) if facts is not None else None

        ok = render_result.slide_count > 0
        if gate_result is not None:
            ok = ok and bool(gate_result["passed"])
        if fact_audit is not None:
            ok = ok and bool(fact_audit["passed"])

        return BuildOutcome(
            ok=ok,
            slide_count=render_result.slide_count,
            ir_path=str(ir_path),
            pptx_path=render_result.path,
            html_path=html_path,
            renderer=render_result.renderer,
            gate=gate_result,
            manifest=manifest,
            fact_audit=fact_audit,
            warnings=warnings,
        )

    def _manifest(self, gate_result: dict[str, Any], *, reference: str | Path | None) -> dict[str, Any]:
        from .delivery import DeliveryReport
        from .manifest import build_manifest

        candidate = str(gate_result.get("candidate") or "")
        report = DeliveryReport(
            passed=bool(gate_result["passed"]),
            iterations=1,
            final_pptx=candidate,
            attempts=[],
            page_gate=gate_result.get("page_gate"),
            critic_gate=gate_result.get("critic_gate"),
            visual_gate=gate_result.get("visual_gate"),
        )
        manifest = build_manifest(report, reference=Path(reference) if reference else None)
        manifest["gate_mode"] = gate_result.get("mode")
        manifest["degraded_gates"] = list(gate_result.get("degraded") or [])
        return manifest
