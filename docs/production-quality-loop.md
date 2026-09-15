# PPT Agent Production Quality Loop

PPT Agent treats the generated PPTX as a build artifact. A deck is not deliverable merely because the generator exits successfully.

## Release rule

**Every slide must pass every required gate. One failed slide blocks the entire delivery.**

Aggregate scores, averages, or a high overall visual score must never hide a failed page.

## Per-generation loop

```text
Task / Sources
     ↓
Story + Slide Plan
     ↓
Universal IR
     ↓
Build PPTX
     ↓
Render ALL slides
     ↓
┌─────────────────────────────────────┐
│ Per-page production gates           │
│                                     │
│ • render success                    │
│ • page count / dimensions           │
│ • geometry / bounds                 │
│ • zero-size / broken elements       │
│ • near-blank detection              │
│ • visual critic                     │
│ • reference regression (if enabled) │
└──────────────────┬──────────────────┘
                   ↓
              All pages pass?
               ↙          ↘
             NO            YES
             ↓              ↓
       Repair requests   Final QA
             ↓              ↓
    Modify source / IR      Manifest
             ↓              ↓
          Rebuild        Deliver PPTX
             ↓
        Render ALL slides
             ↓
           Recheck
```

## Why render the complete deck?

A local change can create a new failure on another slide. For example, changing a shared font, theme, layout rule, master, image asset, or component can affect multiple pages. Therefore a repair is never considered complete until the complete deck has been rendered and revalidated.

## Repair contract

Repair requests identify the exact page and the evidence for failure. A repair implementation should modify the authoritative source representation (IR, content, template rule, or build configuration) and rebuild the PPTX. It should not silently patch the final PPTX as an untracked artifact.

The current `run_repair_loop()` API provides this orchestration contract. A future generation engine will connect it to the Story/Planner/Renderer/Visual Critic components.

## Reference regression

When a known-good reference deck exists, PPT Agent can additionally compare every corresponding rendered page using visual metrics such as SSIM, MAE, and mismatch ratio. This is especially important when learning Template DNA.

For template-learning changes, the fidelity layer preserves OOXML details that high-level PPT libraries may otherwise discard: master/layout inheritance, z-order, groups, custom geometry, gradients, alpha, image crop/source rectangles, relationships, and theme information.

## Development vs production

Development regression tests verify the machinery. Production validation verifies the actual requested deck.

Both use the same fundamental principle:

> **Render first. Judge the rendered result. Repair the source. Rebuild. Judge again.**
