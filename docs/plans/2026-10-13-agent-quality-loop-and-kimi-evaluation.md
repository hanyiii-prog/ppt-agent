# PPT Agent Quality Loop and Kimi Evaluation

## Goal

Finish the model-assisted authoring and visual QA path without fixing one deck's
style into the Agent. Then run the Agent on the supplied hospital report with
the original Kimi prompt, preserve the supplied template and source evidence,
and compare its output with Kimi's deck.

## Design

- Add a direct OpenAI Responses-compatible provider configured only through
  environment variables. The endpoint, API key, text model, optional vision
  model, and reasoning effort remain deployment choices; credentials are never
  serialized into reports or errors.
- Prefer a complete direct-provider configuration, otherwise retain MCP
  Sampling. Vision review is enabled only when a vision model is explicitly
  configured or the host declares image support. Text-only operation must
  disclose deterministic-review limitations.
- Support semantic HTML and scanned/image-based PDF references. Send PDF page
  images only through explicitly declared vision providers and never use them
  as a source of factual claims.
- After a blocking page-gate or visual-critic finding, allow at most two
  page-plan repair rounds. Repairs may change composition fields only; source
  block attribution, factual copy, key messages, and user-supplied plans remain
  unchanged. Rebuild and revalidate the entire deck after each accepted repair.
- Produce a reproducible, inspectable comparison using the exact source
  Markdown, PPTX template, HTML reference when available, and prompt visible in
  the recording. Compare corresponding pages rendered by the same real renderer.

## Implementation Sequence

1. Add provider request, image capability, configuration, and secret-redaction
   tests; add strict storyboard-repair tests.
2. Implement the provider and wire it into MCP generation and narrative tools.
3. Connect blocking QA findings to bounded, source-preserving plan repair and
   full-deck rebuild/revalidation.
4. Update operator documentation and add a focused offline end-to-end test.
5. Run focused and full suites, generate the comparison deck, render both
   outputs, inspect matched pages, and publish a comparison report.
6. Commit and push only task-related tracked files; preserve existing
   untracked workspace files.

## Acceptance Criteria

- API keys never appear in logs, reports, exception messages, or repr output.
- Image bytes are sent only through a provider/host that explicitly declares
  visual support; otherwise deterministic QA runs with a visible warning.
- Invalid or unsafe model repair output is ignored. Source block IDs and slide
  facts remain unchanged across rebuilds.
- Repair is bounded and reports attempts, findings, and remaining failures.
- The comparison identifies the renderer and model path actually used, checks
  content coverage and layout defects, and includes rendered visual evidence.
- Any live Kimi API comparison is clearly distinguished from offline fallback
  output and is run only with a credential that has not been exposed in chat.
