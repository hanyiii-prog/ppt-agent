# PPT Agent Skill

## Mission

Use PPT Agent as the presentation-engineering layer for an AI agent. The host agent supplies task context and model reasoning; PPT Agent owns source analysis, presentation planning, deterministic build, quality gates and repair.

## Entry points

Pick whichever the host supports; all three reach the same code.

| Host surface | How to start |
|---|---|
| MCP | Connect the `ppt-agent-mcp` server, then call `ppt_agent_capabilities` first |
| CLI | `ppt-agent capabilities`, then `ppt-agent build <source.md> -o <out-dir>` |
| Python | `from ppt_agent import PptAgent` |

**Always begin with `ppt_agent_capabilities` / `ppt-agent capabilities`.** It reports which gates this host can actually run and what degrades; assuming a rasteriser exists is the most common way to deliver a deck with unverified pages.

## Required workflow

1. **Inspect** source documents and reference PPTX files before proposing slides.
2. **Extract evidence** and preserve provenance for important numbers, dates and claims.
3. **Define the story**: audience, objective, key message, evidence and slide purposes.
4. **Create Universal Presentation IR** as the source of truth.
5. **Analyze/apply Template DNA** when a reference deck is supplied.
6. **Build deterministically** with a supported renderer.
7. **Render the complete deck** before delivery. Never validate only a sample page.
8. **Run a per-page production gate** on every slide: render success, page count, dimensions, bounds/overflow, zero-size or broken elements, near-blank detection, readability/density checks, and visual consistency.
9. **Run visual fidelity regression** whenever a reference deck or known-good baseline exists. Compare **every page**, not only representative pages. A single failed page blocks delivery.
10. **Repair the source/IR/rules**, rebuild, rerender and recheck the whole deck. Repeat until every page passes or the task is explicitly stopped. Do not hide defects with untracked final-file patches.
11. **Deliver** only the validated presentation and its manifest/evidence artifacts when requested.

The production loop is therefore:

`Plan → Build → Render all pages → Page Gates → Visual Critic → Repair → Rebuild → Render all pages → Page Gates → Final Delivery`

This same loop is used both for development/regression testing and for the final user-facing PPT generation. Development tests prove the machinery works; production validation proves the actual requested deck is acceptable.

## Reading the gate result

A gate response always states which gates ran. Read `mode` and `degraded` before trusting `passed`:

- `"mode": "rendered"`, `degraded: []` — full page, critic and visual-regression gates passed.
- `"mode": "structural"`, `degraded: ["render_preview"]` — bounds, zero-size shapes and empty slides were checked; **image-level problems were not**. Tell the user the visual gates did not run rather than implying a full check.

Never present a structural-only pass as visual validation. See `docs/adapters.md` for the fallback matrix.

## Template DNA requirements

Template DNA is not a statistics report. It must preserve enough information to explain and reproduce the visual system — **per page kind**, because a cover, a TOC, a chapter divider, a body page and a closing page have different layer stacks, different ornaments and different inheritance. Extracting one flat shape list for the whole deck is how a rebuild ends up painting a full-bleed blue rectangle over a white section page.

At minimum, capture when present:

- element geometry, **rotation / flip plus a rotation-aware bbox** (`rendered_bbox`) — `shape.left/top/width/height` describe the *unrotated* frame, so a 90-degree band reads as a tall thin box while painting a wide flat one
- fill, line, **alpha/transparency on every gradient stop, on run colours and on picture fills** (`a:alphaModFix`), gradients (angle, `rotWithShape`, path) and effects
- typography and text-frame inheritance — raw `latin`/`ea`/`cs` typeface references (theme refs like `+mn-ea` kept verbatim), `bodyPr` autofit/insets/anchor
- **the full rendered z-order**: master shapes, then layout shapes, then slide shapes, with one global `render_order` across all three
- placeholders and their layout/master inheritance
- slide background, theme and colour scheme — `a:bg` *declared* vs inherited from the theme (`lt1`)
- slide master and slide-layout properties
- image relationships, crop/source rectangles and asset checksums
- custom geometry / freeform paths and connector definitions
- **page kinds**: `cover` / `toc` / `section` / `content` / `closing`

### Page kinds, and what "chrome" means

`ppt_agent.page_dna.extract_deck_dna()` (schema `template-dna/v0.4`, also reached through `analyze_pptx`) classifies every slide and aggregates DNA per kind. `page_kinds[kind]["ornaments"]` lists the shapes present on **every** page of that kind, **in paint order** — that set *is* the chrome, and it is what a clone must inherit. `frequent` lists near-chrome (layout variants, present on most pages).

```python
from ppt_agent.page_dna import extract_deck_dna, summarize_kind

dna = extract_deck_dna("reference.pptx", include_raw_xml=False)
dna["presentation"]["page_kind_counts"]
# {'cover': 1, 'toc': 1, 'section': 4, 'content': 14, 'closing': 1}
print(summarize_kind(dna["page_kinds"]["section"]))
# #0 [layout] 矩形: 圆角 21 3.5479,-1.9153 3.9111x11.0069 rot=90.0 flip=H \
#    bbox=[0.0, 1.6326, 11.0069, 3.9111] prst=round2SameRect

# diff two decks by kind instead of page by page
kinds = dna["page_kinds"]["content"]["ornaments"]      # 8 chrome shapes, ordered
```

Classification order, most trustworthy first: **position** for the two bookends (a last page reusing the cover layout is `closing`, not a second cover) → **headline text** (`目录` / `CONTENTS`, which must beat the layout name because a TOC routinely reuses the body layout) → **layout name** → **structure** (a rotated band with almost nothing else is a divider; a full-width top bar plus content is a body page). Pass `kind_overrides={4: "toc"}` when the names are not descriptive enough.

Use the OOXML fidelity layer as an escape hatch when `python-pptx` or another high-level library cannot represent a property exactly.

### Count pixels, not strings

A template's *visible* brand colour is the one that covers area — usually painted with **theme colours** (`schemeClr accent1`), not hard-coded hexes. Counting literal `srgbClr` occurrences inverts this: the 天津口腔 template hard-codes a purple `7030A0` in 34 small shapes but paints its brand blue `1185FE` via `accent1` across ~1300 sq in of header bars, cards and tables. The eye says blue; a string counter says purple. `ppt_agent.palette.dominant_colors(path)` resolves `schemeClr` through the theme, weights every fill (including gradient stops) by physical area and buckets results by hue family — trust it over raw counts, and never hard-code a palette in a generator script; read it from the template first. If the deck's own chrome (cloned shells) is blue while your injected shapes are purple, you have built a deck at war with its template.

## Template-page clone route (highest fidelity, use when a template .pptx is supplied)

The DNA route above inherits *palette and typography* but re-draws every page, which loses the template's **composition** — cover photos, logos, freeform decorations, gradient chips, header bars. When the user supplies a real template deck and wants the output to *look like the template*, use the clone-shell route instead:

`ppt_agent.clone_shell.CloneShell` — open a writable copy of the template, classify its slides into shells by layout name (`cover` / `section` / `content` / `close`), hand one shell out per planned page, clear the body (keep the title placeholder), inject native content, then prune unused slides and reorder. The untouched chrome is byte-identical to the template — no re-rendering, no approximation. **The chrome lives in the layouts and keeps rendering after `clear_body`: never redraw it, and never drop `rot`/`flip` when you do re-create a decoration** (see the two sections below).

```python
from ppt_agent import CloneShell
from ppt_agent.clone_shell import set_title

deck = CloneShell("template.pptx")            # role map overridable via role_map=
ok, problems = deck.plan_capacity({"section": 4, "content": 20})
i0, cover = deck.take("cover", cleared=False) # keep the photo cover intact
for page in body_pages:
    idx, sl = deck.take("content")            # body cleared, title placeholder kept
    set_title(sl, page.title)                 # write into the title placeholder
    ... draw native shapes into sl ...
deck.finish("out.pptx")                        # prune + reorder + save
```

**Always audit before delivery** — out-of-bounds checking alone is not enough; text overflow hides in plain geometry:

```python
from ppt_agent.clone_shell import audit_pages
issues = audit_pages(deck.prs)   # overflow / collision / empty / duplicate / doubling
```

This caught a real framework-page overflow (7 items squeezed into 1.14in cards) that passed every bounds check, and the `doubling` kind catches slide shapes painted on top of the *layout's own* decoration (see "INHERIT, do not redraw"). Zero issues is the delivery bar.

The `duplicate` check distinguishes the two things a naive text-count conflates: a string painted **exactly twice** is the chip-label-also-drawn-beside-it bug and is always flagged; the same **short** label on 3+ cards (`关注核心` / `业务特征与难点`) is a card-template field header and is exempt. Any **long** string (≥12 CJK cols) repeated at all is still flagged.

Verified on the 专病数据库 deck: cover colour-signature distance vs template dropped **83.5 → 6.4** (plain-IR route → clone route). Pair it with these composition primitives that the V4 generator proved out — they are the difference between "a deck" and "a produced deck":

- **Breadcrumb titles** — `一、建设背景与初步方案 | 建设背景` in the title placeholder, so every page states its chapter context.
- **A dedicated TOC page** — `CONTENTS` label + numbered icon rows + per-chapter one-line summaries.
- **Icon blocks** — brand-colored rounded squares with a white glyph/number (`CloneShell` doesn't draw these; add a helper alongside).
- **Density trimming** — split long body paragraphs on `；`, rejoin with ` · `, cap ~120 chars; short phrases read as "executive deck", full sentences read as "document dump".

When neither route is clearly better, ask: is the template's *look* the deliverable (clone) or just its *brand colors* (DNA)? Default to clone when a template file is in hand.

### Content-page chrome: INHERIT, do not redraw (corrected in v1.7.0)

The single most expensive mistake of the V6→V9 series was re-drawing chrome that the template **layout already paints**. On the clone route the shell's layout supplies the top wash, the two dots, the hairline and both logos; painting them again onto the slide does not "add" chrome:

- **Logos double-print** at identical coordinates (the layout copy plus yours).
- **The wash degrades.** The template bar is `accent1 @15% → @0%` alpha fading right; re-emitted as a solid `1185FE` rect it becomes a hard blue band. A reviewer's verdict on V8 was exactly this: *"内容页里使用的控件和布局，也比 kimi 生成的差"*.
- **The slide title ended up in the wrong place.** Kimi's content title is at `L=0.54 T=0.15` (i.e. *on* the wash, as the layout intends); moving it to `T=0.80` to "fix contrast" broke the match.

Correct API:

```python
from ppt_agent.clone_shell import (add_content_chrome, set_title, layout_chrome,
                                   rebuild_cover, audit_pages)

inv = layout_chrome(slide)          # {'bar','divider','dots','pictures','rotated'}
add_content_chrome(slide, prs=deck.prs)   # returns 0 when the layout already has it
set_title(slide, "二、建设计划 | 总体技术架构")   # leave the layout slot alone
```

`add_content_chrome` clears the shell's stray decorations, then **returns 0 without drawing** whenever `layout_chrome` reports a bar + logos. Pass `force=True` only for shells whose layout has no chrome. `audit_pages` now emits a `doubling` issue for any slide shape that coincides with a layout decoration — that check is what pins this rule down.

Still valid from v1.5.0: **cover z-order** must be rebuilt bottom-up (background photo → freeform bands → logos → label pill `round2DiagRect` → 44pt title → meta); `rebuild_cover(...)` encodes it. `box()`, `set_geom(shape, 'round2DiagRect'|'cloud'|'homePlate')` and the **思源雅黑** default typography are unchanged.

### Rotation and flip are first-class (v1.7.0)

python-pptx's `shape.left/top/width/height` have **nowhere to store `rot` / `flipH` / `flipV`** — they are silently dropped on every read-modify-write. The template's section-page chapter band is `3.91x11.01in` with `rot=5400000 flipH=1`, so it renders as an *11.01x3.91in horizontal banner*; re-drawing it from the frame numbers produces a vertical stripe 90° off. Every layout/overlap/overflow decision must use the rendered box, not the frame:

| Need | Use |
|---|---|
| read rotation/flip | `shape_rot(shape) -> (deg, flipH, flipV)` |
| write position + rotation | `set_xfrm(shape, x, y, w, h, rot=90, flip_h=True)` |
| rendered box for layout maths | `rotated_bbox(shape) -> (L, T, W, H)` |
| reuse a decoration verbatim | `clone_shape(layout_shape, slide)` — deep-copies XML incl. rot/custom geometry |
| inspect what a layout inherits | `layout_chrome(slide)` |

`audit_pages` uses `rotated_bbox` throughout, so a rotated banner can no longer "pass" bounds checks while covering the title.

Also in v1.7.0: `gradient_fill` accepts `(pos, hex, alpha_pct)` stops (opacity, not alpha) and `rot_with_shape=` — needed to reproduce the template's translucent wash instead of a solid band.

### Cover AND closing reuse the shell's media (v1.8.0)

The bookends are where a redraw does the most damage, because their whole design *is* cloned media:

- **Cover** — `rebuild_cover(slide, prs=..., pill_text=..., title_text=..., meta_text=...)`: background photo → 2 translucent freeform waves → logos → pill → 44pt title → meta. Draw bottom-up; the logo goes *before* the title, and the hospital name is its own pill, never merged into the title.
- **Closing** — `rebuild_closing(slide, prs=..., title_text=..., sub_text=..., meta_text=...)`: a closing page almost always reuses the *cover* shell, so the photo and the two wave bands (freeforms at `0061FA @75% -> @0`) are already on the slide. Capture and re-append them; write the three lines **centred**; leave the lower half **white**.

What V9 got wrong: it cleared the body and then painted a full-page opaque gradient plus an opaque rounded rect. The photo disappeared, the waves lost their alpha, and the closing page rendered solid blue — while the cover beside it was correct. If your closing page has no photo and no transparency, you redrew it.

The same trap catches small decorations. A page-type DNA diff of a TOC found our decorative circle painted **opaque** (`1185FE -> 0B6FE0`) where the reference used `1185FE @7.843% -> @1.961%` — an opaque 4.44in circle covering the chapter items' text. Faint washes are load-bearing: **read the alpha off the reference, never assume a decoration is solid.** The fix is one call — `gradient_fill(circle, [(0, "1185FE", 7.843), (100, "1185FE", 1.961)], angle=45)`.

When the *layout* owns the decoration, restyle it in place rather than drawing a second copy (a copy trips `audit_pages`'s `doubling` check): iterate `slide.slide_layout.shapes`, find the shape by `prstGeom`, and re-fill it. That is how the chapter band was moved from the template's flat `accent1` to the reference's `70B6FE -> 1185FE` @45°.

Content patterns worth copying: five-layer architecture ladders read top-down as **L5(应用端) → L1(数据底座)** with design principles in a right sidebar; data-model pages lead with hero numbers (15 业务域 / 58 实体表 / 5 底座模型) before the detail cards.

### Empty placeholders are dead DNA — delete them (v1.9.0)

A placeholder kept-but-blank is **not inert**. PowerPoint resolves an empty slide placeholder against its layout twin, so a leftover empty title slot makes the renderer paint the layout's skeleton string (``单击此处编辑母版标题样式``) across the top of the page. And most template shells carry a *filled* title placeholder, so a hand-built header that "ignores" it still leaves the template's stale heading ("一、项目总览") showing through.

A page whose header/body is hand-drawn **owns the whole page**: remove every placeholder it does not write to.

| Need | Use |
|---|---|
| list leftover placeholders | `drop_empty_placeholders(slide)` (also removes *filled* title slots) |
| check what a layout would resolve to | `layout_placeholder_text(slide, idx)` |
| build a TOC / divider body | `K.toc_page(slide, title, chapters, ...)` — inherits chrome, drops placeholders, draws circle + numbered items |

`audit_pages` emits **`stale_placeholder`** for any slide whose title placeholder is present but blank while its layout twin has text — the check that catches this class. Read the count drop: on the 专病 deck the TOC shell went 26 → 25 shapes once the slot was deleted, and only then did the page stop showing a stray heading.

### Page kits — layout patterns from the Kimi v1→v2 revision (v1.6.0)

`ppt_agent.page_kits` packages the layout patterns a reviewer asked for in the second revision of the 专病 deck ("一眼看懂", graphic timeline). Each kit draws a full content page body on the shared chrome and takes plain data:

| Kit | Replaces | Pattern |
|---|---|---|
| `content_header(slide, title, lead)` | manual title/lead | chrome + title/lead at the reference grid; returns the content top |
| `chapter_page(slide, title, items)` | hand-painted divider | inherits the layout's rotated band (no page fill, no redraw) + centred title + hairline + N list lines |
| `toc_page(slide, title, chapters)` | hand-built TOC | inherits chrome, **drops placeholders**, faint decorative circle + numbered items + hairline rules |
| `four_role_cards(slide, cards, note)` | a RACI **table** | 4 bordered cards: gradient header + icon + role chip + bulleted duties + note bar |
| `org_chart(slide, top, groups, depts, note)` | a flat person list | top pill → connector bus → 2 group columns (left chip + right stacked nodes) → department cards |
| `two_panel_list(slide, left, right)` | long prose | two bordered panels with gradient headers; left = icon rows, right = light sub-panels |
| `quad_cards(slide, cards)` | 4 stacked rows | 2×2 icon cards (`QUAD_CARD` 5.972x2.639) |
| `column_cards(slide, cards, bottom=)` | uneven columns | N equal columns, optional gradient heads, optional full-width bottom panel |
| `stage_cards(slide, stages, current)` | a text timeline | `homePlate` stage arrows + task list + milestone badges |
| `progress_timeline(slide, steps, note)` | bullet dump | dated rows with 3-state status chips (`done`/`doing`/`plan`) + "当前阶段" marker + note bar |
| `stage_timeline(slide, stages, current, note)` | a text timeline | orange "current" banner + `homePlate` arrow stages + task columns + milestone badges |

Two rules the reviewer enforced, worth keeping:

- **Glanceable > complete.** When a table needs explaining ("讲解的时候也不好讲解"), redesign it as cards. `four_role_cards` was a RACI table in v1.
- **Mark the present.** Any timeline must show where "now" is — `stage_timeline` takes a `current=` banner and `progress_timeline` an orange `doing` chip with `current=True`.

```python
from ppt_agent import page_kits as K

K.four_role_cards(sl, cards, "协同机制：四方已入项目群，朗视对接两步走。",
                  title="二、建设计划 | 多方协同与职责分工", lead="临床定标准，信息科做统筹")
K.org_chart(sl, "院领导：马文盛", groups, depts, "病种牵头人职责：…",
            title="二、建设计划 | 项目组织架构", lead="院领导挂帅，卫宁团队负责交付")
K.stage_timeline(sl, stages, "当前：标签收集与方案细化（9 月，进行中）", "责任分工：…",
                 title="四、下一步计划 | 总体时间节点", lead="10 月出程序 · 12 月初交付")
```

Content corrections the same revision made: a pilot count stated as 2 when the source says 3; passing mentions of an unrelated review/rating programme that must be deleted deck-wide (task count 11 → 10); and "下一步计划" must not repeat a month already covered by "近期推进工作". Re-read the source before trusting a previous draft's numbers.

## Non-negotiable guardrails

- Never invent metrics, dates, quotations or business conclusions.
- Prefer supplied source material over model memory.
- Important claims should carry provenance whenever the source format permits it.
- The final PPTX is a build artifact; the IR and source evidence are authoritative.
- Keep output reproducible where practical: same inputs + version + configuration should produce equivalent structure.
- Avoid repetitive card grids when the content does not justify them; choose layouts from content semantics and template grammar.
- Preserve editability for native PPTX elements whenever the chosen renderer supports it.
- Host agents are adapters. Do not make core presentation logic dependent on a single model or platform.
- A script that exits successfully is **not** sufficient visual validation. A rendered deck must pass the per-page production gate before delivery.
- If visual regression is enabled, **zero failed pages is the release criterion**. Aggregate averages must never hide a bad slide.
- Treat the MCP `--workspace` root as a hard boundary for outputs.

## Capability routing

If the host exposes a native PPTX or Office capability, use it where it materially improves fidelity. Otherwise use the portable local renderer. If visual rendering is available, use it for QA before delivery.

Choose the renderer deliberately:

- `native-pptx` — editable `.pptx`. The default whenever python-pptx is installed.
- `html` — self-contained, printable preview. Use it for fast visual iteration and when the host cannot open a deck.

## Commands (V1.0)

```bash
ppt-agent capabilities                                    # what can this host do?
ppt-agent markdown-to-ir input.md -o workspace/presentation.json
ppt-agent analyze-pptx reference.pptx -o workspace/template-dna.json
ppt-agent ir-to-pptx workspace/presentation.json -o output.pptx
ppt-agent ir-to-html workspace/presentation.json -o preview.html
ppt-agent qa-ir workspace/presentation.json
ppt-agent validate-pptx output.pptx -o workspace/page-gate.json
ppt-agent visual-regression reference.pptx output.pptx -o workspace/visual-report.json
ppt-agent audit-facts workspace/presentation.json --facts facts.json
ppt-agent build input.md -o workspace --stem deck --facts facts.json
ppt-agent benchmark benchmarks/cases -o workspace/benchmark-report.json
ppt-agent-mcp --workspace workspace
ppt-agent-release build --root .
```

`ppt-agent build` is the whole loop in one call: plan, render, gate and emit the manifest plus the
HTML preview. Prefer it over chaining subcommands by hand.

## Fact lock

`--facts` / the `facts` argument takes a registry of `{claim, source_id, locator}` entries. Every
textual claim in the deck is checked against it and the build fails when a claim is unsupported. Register
the claims you actually sourced; a partial registry will correctly block the build rather than pass
silently.
