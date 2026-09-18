# PPT Agent Roadmap

Status legend: `[x]` shipped in code, `[~]` partial / v1 scope, `[ ]` not started.

## V0.1 — Foundation
- [x] GitHub repository
- [x] Portable Skill contract
- [x] Universal Presentation IR schema (`ir/presentation.schema.json`)
- [x] Typed Python IR models (`ppt_agent.ir`, with `to_dict`/`from_dict` round trip)
- [x] Initial CLI
- [x] GitHub Actions test workflow
- [x] PPTX inspection baseline (`ppt_agent.template.analyze_pptx`)
- [x] First end-to-end sample (`tests/test_render_e2e.py`)

## V0.2 — Template DNA
- [x] reference PPTX structural extraction
- [x] typography/color/spacing inventory
- [x] page-type clustering (first/body/last roles)
- [x] reusable layout grammar (`ppt_agent.visual_grammar`)
- [x] OOXML fidelity capture (alpha / z-order / group / raw XML)
- [x] DNA → IR conversion (`ppt_agent.dna_to_ir`)

## V0.3 — Build + Visual QA
- [x] native editable PPTX renderer (`ppt_agent.renderer`)
- [x] deterministic rendering (single code path, no randomness)
- [x] geometry checks (`ppt_agent.page_validation`)
- [x] contact-sheet visual review (`ppt_agent.visual_regression`, `visual_critic`)
- [x] `ir-to-pptx` CLI command

## V0.4 — Evidence Safety
- [x] Fact Registry (`ppt_agent.fact_registry`)
- [x] provenance graph (claims carry `Provenance`)
- [x] Fact Lock (support audit via `audit_presentation`; `ppt-agent audit-facts`)
- [x] source-to-slide traceability (`Provenance.locator` preserved end to end)

## V0.5 — Critic + Repair
- [x] visual critic (`ppt_agent.visual_critic`)
- [x] layout/density scoring (`ppt_agent.visual_critic`, `visual_grammar`)
- [x] targeted repair tasks (`delivery._repair_requests`)
- [x] bounded rebuild loop (`delivery.run_repair_loop`)
- [x] renderer build callback (`Renderer.build_callback`)

## V0.6 — Story + Agent Interoperability
- [x] Story Architect (`ppt_agent.story`)
- [x] MCP server (`ppt_agent.mcp`, dependency-free stdio transport, 10 tools)
- [x] generic adapter (`ppt_agent.adapters.HostAdapter`, `GenericAdapter`, `LocalAdapter`)
- [x] capability negotiation (`ppt_agent.contracts.negotiate`, `HostAdapter.effective`)

## V0.7 — Host Adapters
- [x] Codex (host profile)
- [x] WorkBuddy (host profile)
- [x] 豆包工作 (host profile)
- [x] Claude (host profile)
- [x] ChatGPT (host profile)
- [x] additional agent hosts (declarative profiles via `create_adapter` / `HostAdapter`)

## V1.0 — Stable Platform
- [x] stable IR contract (`ppt_agent.contracts`, `ir_version` stamp, `supported_ir_versions`)
- [x] renderer SDK (`ppt_agent.renderers`: protocol, registry, preference order, HTML visual engine)
- [x] adapter SDK (`ppt_agent.adapters`, capability descriptor schema)
- [x] benchmark suite (`ppt_agent.benchmark`, `benchmarks/cases`, determinism assertions)
- [x] reproducible release process (`ppt_agent.release`, `scripts/release.py`, `release.yml`)
- [x] unified SDK facade (`ppt_agent.sdk.PptAgent`) shared by CLI, MCP and integrations

## V1.1 — Designed output
- [x] theme token system (`ppt_agent.theme`: palette, type scale, rhythm, named themes)
- [x] design layer (`ppt_agent.design`: cover / agenda / content / section / closing layouts)
- [x] design composed in IR, so the native and HTML engines share one design
- [x] template-injected slides (explicit geometry) pass through untouched
- [x] PPTX → PNG rasteriser (`ppt_agent.preview`, Pillow backend)
- [x] visual gates upgrade from structural to rendered whenever a rasteriser exists
- [x] `build --preview` flag and the `preview` CLI command

## V1.2 — Template-driven design
- [x] Template DNA → theme tokens (`ppt_agent.theme.theme_from_dna`)
- [x] palette, font stack and type scale read from the reference deck
- [x] `build --template` on the CLI and a `template` argument on the MCP build tool
- [x] theme recorded in the IR, so a later `ir-to-pptx` reproduces the same design
- [x] stock Office dark slots rejected when they fall outside the brand hue family

## V1.3 — Area-weighted palette
- [x] `ppt_agent.palette`: schemeClr resolved through the theme, colours weighted by painted area
- [x] `analyze_pptx` emits `dominant_palette`; `theme_from_dna` prefers it over literal srgbClr counts
- [x] a deck painted mostly with theme accent1 no longer misreads as its minority hard-coded colour

## V1.4 — Clone-shell route
- [x] `ppt_agent.clone_shell.CloneShell`: classify template slides into shells by layout name,
      hand out cleared bodies, prune unused shells and reorder
- [x] shared primitives: `box`, `copy_logos`, `set_geom` (raw `prstGeom` patching), `gradient_fill`
- [x] per-page layout audit (`audit_pages`: overflow / collision / empty / duplicate)

## V1.5 — Cover & content chrome
- [x] `rebuild_cover`: photo → freeform bands → logos → label pill → 44pt title → meta z-order
- [x] `add_content_chrome` (clear → bar → dots → divider → logos) and title repositioning
- [x] default typography 思源雅黑

## V1.6 — Page kits
- [x] `ppt_agent.page_kits`: content header, four role cards, org chart, two-panel icon list,
      dated progress narrative with status chips, homePlate stage timeline
- [x] duplicate-audit refinement: exactly-2 occurrences = bug, ≥3 short strings = card field labels

## V1.7 — Rotation as a first-class citizen
- [x] `set_xfrm` / `shape_rot` / `rotated_bbox` / `clone_shape` — `left/top/width/height` do not
      carry `rot`/`flip`, and re-drawing from the unrotated frame was the most expensive bug class
- [x] gradient stops accept per-stop alpha + `rot_with_shape` (the template's header is an
      `@15% → @0%` translucent wash, not an opaque band)
- [x] inherit-don't-redraw: `layout_chrome()` probe; `add_content_chrome` draws nothing when the
      layout already paints the chrome; `audit_pages` gains the `doubling` check
- [x] kits: chapter page, 2×2 quad cards, N-column cards, homePlate stage cards

## V1.8 — Per-page-kind Template DNA (v0.4)
- [x] `ppt_agent.page_dna`: `template-dna/v0.4` — cover / toc / section / content / closing DNA
      over the full master → layout → slide stack with one global render order
- [x] full attribute capture: preset geometry + adj (or custGeom census), rotation/flip with a
      rotation-aware bbox, per-stop gradient alpha, run colour alpha, picture `alphaModFix` +
      crop + media fingerprint, line caps/heads/joins, effects, `p:bg` declared vs inherited
- [x] page-kind `ornaments`: the shapes present on every page of a kind = the chrome to inherit
- [x] `rebuild_closing` reuses the shell's own media (photo + translucent wave bands) instead of
      redrawing an opaque full-bleed background

## V1.9 — TOC kit & placeholder hygiene
- [x] `toc_page` kit reproducing the reference TOC geometry (translucent deco circle included)
- [x] `drop_empty_placeholders` + `layout_placeholder_text`; `clear_body(keep=...)` for pages that
      own their header
- [x] `audit_pages` gains `stale_placeholder`: an empty placeholder resolves back to its layout
      twin, so the layout's skeleton prompt (`单击此处编辑母版标题样式`) gets painted — drop it,
      don't blank it

## V1.10 — Clone route on the MCP surface
- [x] `ppt_agent.clone_build`: a JSON page plan → `CloneShell` buckets → kit dispatch → audit;
      kit kwargs are the `page_kits` signatures verbatim, named errors for bad roles/kits/missing
      data/insufficient shells before any file is written
- [x] SDK: `PptAgent.clone_plan` / `clone_build` / `clone_audit`
- [x] MCP tools `ppt_agent_clone_plan` / `ppt_agent_clone_build` / `ppt_agent_clone_audit`
      (13 tools total) — the byte-identical-template route needs no Python from the host agent
- [x] `quad_cards` note fix: with a note bar the card rows compress to clear it; without one the
      exact reference geometry is kept (the note used to overlap the second row by ~0.6in)

## V1.11 — Fidelity Engine closed loop (branch `v1.11-fidelity-engine`)
- [x] `ppt_agent.fidelity_model`: canonical `DeckFidelity` / `SlideFidelity` / `ElementFidelity`
      model — every element knows its source (master/layout/slide), global render order, resolved
      style and raw OOXML evidence
- [x] Extractor hardening (`fidelity.py` → `template-dna/fidelity/v2`): per-kind `cNvPr` identity,
      rotation/flip/**group-transform-mapped rendered bboxes**, theme colour resolution
      (schemeClr → RGB), structured fill/gradient/typography/bodyPr/custGeom/connector/table,
      placeholder inheritance chains (declared/inherited/resolved/source), page-kind
      classification and a **TOC structure fingerprint**
- [x] `ppt_agent.fidelity_match`: seven-priority identity matching (semantic identity /
      placeholder / name / media hash / role / geometry proximity / index fallback) — reorders and
      insertions no longer cascade into false property diffs
- [x] Structural Diff 2.0 (`fidelity_diff.py`): eight-group diff codes (page/layer/geometry/style/
      text/media/inheritance/structure), namespace- and attribute-order-insensitive **semantic XML
      hashes**, media compared by content hash, assets compared order-independently
- [x] `ppt_agent.fidelity_repair_executor`: zip-level **minimal property repair** addressed by
      `cNvPr` id (one `x` for a position, one `<a:alpha>` for transparency), per-container
      layer-order rebuild, verify-by-re-extraction; non-minimal directives (added layers, media
      swaps, page kinds) are reported `skipped`, never faked
- [x] Visual Diff 2.0 (`visual_regression.py`): explicit
      `renderer_unavailable` / `renderer_error` / `visual_pass` / `visual_fail` states, Edge Diff,
      8-region diff (background/header/title/body/footer/image/decoration/chrome),
      `page_score` / `critical_region_score` and the **Critical Region Gate** (a lost logo can no
      longer hide behind a high whole-page SSIM)
- [x] Iterative repair (`fidelity_pipeline.py`): `repair_deck` with `max_iterations` (default 3),
      full `repair_history`, `A→B→A` / stalled-repair **oscillation detection** and
      `FidelityRepairExhausted` carrying the remaining issues
- [x] Clone route integration (`clone_build.py`): `chrome_fidelity_gate` proves every finished
      page still inherits the template's layout/master layers verbatim and TOC fingerprints
      survive the chain
- [x] CLI `ppt-agent fidelity extract|diff|audit|repair|validate`; MCP tools
      `ppt_agent_fidelity_extract` / `diff` / `repair` / `validate` (17 tools total)
- [x] Real-PPTX regression suite: 13 single-property mutation fixtures + 5 TOC fixtures + the
      end-to-end loop (diff → repair → re-extract → structural gate → render → visual gate),
      355 tests green

## V2.0.0 — Fidelity Engine GA (released, main)

The V1.11 Fidelity Engine branch is promoted to the `2.0.0` GA line on `main`. This is a **major
bump** because the fidelity surface is now a first-class, versioned contract (extraction schema
`template-dna/fidelity/v2`, visual four-state status, critical-region gate) rather than an internal
helper.

- [x] Version promoted `1.11.0` → `2.0.0` across `pyproject.toml` and `ppt_agent.__version__`
- [x] CI hardening: `python-tests` now installs `fonts-noto-cjk` (real CJK rendering) and surfaces
      `FAILED`/`ERROR` lines as `::error::` annotations so a red run names the exact case
- [x] Render-path bug fixed: `visual_regression.render_pptx` now coerces `str` paths to `Path`
      (the LibreOffice branch used `pptx.stem`, which crashed only when a real renderer was present)
- [x] `benchmark-and-mcp` job asserts `17` MCP tools end-to-end through the stdio handshake
- [x] 355 tests green on Python 3.10 / 3.11 / 3.13; `dependency-free-core` import-and-capabilities
      gate passes with no presentation engine installed

## Renderer v1 scope

The native renderer (`src/ppt_agent/renderer.py`) consumes Universal IR and emits an editable `.pptx`:

- Absolute placement when a component carries `x/y/w/h` (inches); deterministic top-down flow otherwise.
- Component types: `text`, `paragraph`, `title`, `shape`, `image`, `table`, `chart`, `group`.
- Style mapping: solid fill + transparency (OOXML `a:alpha`), line color/width, font size/bold/italic/name/color/alignment.
- Slide background fill, speaker notes, per-deck slide size from `theme.slide_size_inches`.
- Group components recursively render their captured children.

Layout is resolved once in `ppt_agent.styling.resolve_layout()` and consumed by both the native and HTML
engines, so a cross-engine comparison compares fidelity rather than two layout algorithms.

The HTML engine (`src/ppt_agent.renderers/html.py`) emits one self-contained, printable deck: inline
styles, base64-inlined assets, escaped text, `@media print` page breaks.

## Design layer scope

Since V1.1 the render path is:

```text
semantic slide → design.design_presentation() → positioned, styled IR → per-renderer draw
```

- Layouts shipped: `cover`, `agenda`, `content`, `section`, `closing`.
- Page purpose is resolved from English or Chinese headings (`封面`, `目录`, `总结`, `章节`, …).
- A heading that names a layout rather than carrying content (`## 封面`) is treated as a marker; the
  real cover headline comes from the paragraphs underneath it.
- Any slide whose components already carry `x/y/w/h` (Template DNA path) bypasses the design layer.

- Theme tokens can come from a reference deck: `theme_from_dna()` maps the Template DNA palette,
  font stack and type scale onto the token set, so `build --template` restyles the deck without
  touching layout code. Layout rhythm keeps the defaults — DNA carries per-shape geometry rather
  than a versioned rhythm, and guessing one would be less faithful than not guessing at all.

## Known limits

Tracked for the next cycle:

- gradient fills fall back to solid in both design-layer engines (the clone-shell route
  `clone_shell` + `page_kits` emits gradients and alpha natively)
- `chart` components render as labelled placeholders on both engines
- embedded image bytes require `data.bytes`/`data.path`
- flow layout estimates text height arithmetically rather than measuring glyphs, so a very long single
  block can still overflow; the page gate catches it rather than the layout preventing it
- the HTML engine positions text boxes from the same layout as the native engine, so text that spills
  in the browser does not reflow the following blocks
- the design layer ships five page archetypes; richer ones (metric cards, comparison, timeline) are
  not implemented yet, so a dense list still renders as a list
- the Pillow rasteriser is a fidelity preview, not a pixel-accurate Office renderer: gradients, shadows
  and 3-D effects are approximated, and text metrics come from the installed CJK font

## Contract compatibility policy

- `IR_SCHEMA_VERSION` `1.0` is current; dialects in `SUPPORTED_IR_VERSIONS` remain readable.
- A dialect is only removed with a major bump and a migration note here.
- `0.1` is retained so decks written by V0.x still load.
