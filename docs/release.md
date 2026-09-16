# Release Process

A release has to answer one question before anything else: **is what we are shipping exactly what we
tested?**

```bash
python scripts/release.py check-version      # version strings agree across the repo
python scripts/release.py build              # write dist/release-manifest.json
python scripts/release.py verify             # prove the tree still matches the manifest
python -m build                              # sdist + wheel
```

`ppt-agent-release` exposes the same three subcommands, and `.github/workflows/release.yml` runs them
on every `v*` tag.

## What the manifest contains

No timestamps, no host names, no absolute paths — two builds of the same tree produce byte-identical
output, so the manifest can be diffed between machines and checked into CI artifacts.

```json
{
  "schema_version": "1.0",
  "package_version": "1.0.0",
  "core_api_version": "1.0",
  "ir_schema_version": "1.0",
  "adapter_protocol_version": "1.0",
  "benchmark_schema_version": "1.0",
  "supported_ir_versions": ["0.1", "1.0"],
  "file_count": 63,
  "total_bytes": 5123456,
  "digest": "9f2c...e41a",
  "files": [{"path": "src/ppt_agent/sdk.py", "sha256": "...", "bytes": 7123}]
}
```

`digest` is a SHA-256 over the ordered `path\0sha256` pairs, so it changes if a file changes, is added,
is removed, or is renamed.

## The release surface

`RELEASE_DIRECTORIES` defines what ships: `src`, `tests`, `benchmarks`, `scripts`, `ir`, `schemas`,
`skills`, `docs` and `.github`, plus `README.md`, `ROADMAP.md`, `pyproject.toml` and a `LICENSE` when
one exists.

Caches and build output never enter the manifest: `__pycache__`, `*.pyc`, `.pytest_cache`, `build`,
`dist`, `*.egg-info` and virtual environments are excluded, as is the manifest itself.

## Verify is a drift alarm

`verify` compares the working tree against the manifest and reports all three kinds of drift:

```
missing:    docs/guide.md
changed:    src/ppt_agent/sdk.py
unexpected: docs/new-page.md
```

Exit code `0` means the tree is identical, `2` means it is not. CI runs `verify` immediately after
`build`, which catches the classic mistake of shipping a tree that changed between the two steps.

## Version consistency

`check-version` asserts that `pyproject.toml`'s `[project] version` matches `ppt_agent.__version__` and
that `IR_SCHEMA_VERSION` is listed in `SUPPORTED_IR_VERSIONS`. `build` refuses to run when this fails,
so a release can never be stamped with two different versions.

## Changing a contract version

1. Bump the constant in `src/ppt_agent/contracts.py`.
2. Add the previous value to `SUPPORTED_IR_VERSIONS` when the change is backwards compatible — never
   remove a dialect consumers might still be writing.
3. Update `ir/presentation.schema.json` and `schemas/capability-descriptor.schema.json`.
4. Bump `version` in `pyproject.toml` and `__version__` in `src/ppt_agent/__init__.py`.
5. Run `pytest`, then the benchmark, then `release.py check-version`.
6. Note the migration in `ROADMAP.md`.

## Reproducibility contract

- Same IR in, same shape tree out (`renderer.py` has one code path and no randomness).
- Same Markdown in, same IR, PPTX and HTML out — asserted per case by `ppt-agent benchmark`.
- Same tree in, same release digest out.

`ppt-agent benchmark benchmarks/cases -o dist/benchmark-report.json` proves the first two; `verify`
proves the third.
