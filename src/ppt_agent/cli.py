from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .ir import Presentation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ppt-agent",
        description="Portable agent-native presentation engineering framework",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    validate = sub.add_parser("validate-ir", help="Validate basic IR structure")
    validate.add_argument("path", type=Path)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "validate-ir":
        payload = json.loads(args.path.read_text(encoding="utf-8"))
        required = {"version", "metadata", "slides"}
        missing = required - payload.keys()
        if missing:
            parser.error(f"IR missing required fields: {sorted(missing)}")
        if not isinstance(payload["slides"], list):
            parser.error("IR 'slides' must be an array")
        print(f"valid IR: {len(payload['slides'])} slides")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
