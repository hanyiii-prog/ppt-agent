#!/usr/bin/env python
"""Write or verify a deterministic release manifest.

Runs the same code path as `ppt-agent release-manifest` / `release-verify`, so a
local check and a CI check can never disagree.

    python scripts/release.py build
    python scripts/release.py verify
    python scripts/release.py check-version
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ppt_agent.release import main  # noqa: E402

if __name__ == "__main__":
    argv = sys.argv[1:] or ["build"]
    if not any(argument.startswith("--root") for argument in argv):
        argv += ["--root", str(REPO_ROOT)]
    raise SystemExit(main(argv))
