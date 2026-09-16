"""Deterministic release manifest and drift verification.

Two builds of the same source tree must produce the same digest, so the
manifest deliberately contains no timestamps, host names or absolute paths.
`verify` then turns the manifest into a drift alarm: any changed, missing or
unexpected file under the release surface fails the check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .contracts import (
    ADAPTER_PROTOCOL_VERSION,
    BENCHMARK_SCHEMA_VERSION,
    CORE_API_VERSION,
    IR_SCHEMA_VERSION,
    RELEASE_SCHEMA_VERSION,
    SUPPORTED_IR_VERSIONS,
)

# Directories that make up the release surface, in a fixed order.
RELEASE_DIRECTORIES: tuple[str, ...] = (
    "src",
    "tests",
    "benchmarks",
    "scripts",
    "ir",
    "schemas",
    "skills",
    "docs",
    ".github",
)

# Files at the repository root that are part of the surface.
RELEASE_ROOT_FILES: tuple[str, ...] = (
    "README.md",
    "ROADMAP.md",
    "pyproject.toml",
    "LICENSE",
    "LICENSE.md",
)

_EXCLUDED_DIRECTORIES: frozenset[str] = frozenset({
    "__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "build", "dist", ".venv", "venv", "node_modules", ".idea", ".vscode",
})
_EXCLUDED_SUFFIXES: tuple[str, ...] = (".pyc", ".pyo", ".pyd", ".egg-info")


@dataclass(frozen=True)
class FileEntry:
    path: str
    sha256: str
    bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "bytes": self.bytes}


def _is_excluded(path: Path) -> bool:
    if any(part in _EXCLUDED_DIRECTORIES for part in path.parts):
        return True
    if any(part.endswith(".egg-info") for part in path.parts):
        return True
    return path.suffix in _EXCLUDED_SUFFIXES


def iter_release_files(root: str | Path) -> list[Path]:
    """Every file in the release surface, sorted and free of caches."""
    base = Path(root).resolve()
    collected: list[Path] = []

    for relative in RELEASE_DIRECTORIES:
        directory = base / relative
        if not directory.is_dir():
            continue
        for candidate in directory.rglob("*"):
            if candidate.is_file() and not _is_excluded(candidate.relative_to(base)):
                collected.append(candidate)

    for name in RELEASE_ROOT_FILES:
        candidate = base / name
        if candidate.is_file():
            collected.append(candidate)

    return sorted(set(collected), key=lambda item: item.relative_to(base).as_posix())


def file_digest(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(chunk)
    return digest.hexdigest()


def aggregate_digest(entries: Iterable[FileEntry]) -> str:
    """Digest over the ordered (path, sha256) pairs, so it is order-stable."""
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(f"{entry.path}\0{entry.sha256}\n".encode("utf-8"))
    return digest.hexdigest()


def check_versions(root: str | Path | None = None) -> list[str]:
    """Verify the package version and pyproject version agree with the contracts."""
    from . import __version__

    errors: list[str] = []
    if root is not None:
        pyproject = Path(root) / "pyproject.toml"
        if pyproject.is_file():
            text = pyproject.read_text(encoding="utf-8")
            match = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.MULTILINE)
            if match is None:
                errors.append("pyproject.toml has no [project] version")
            elif match.group(1) != __version__:
                errors.append(
                    f"version mismatch: pyproject.toml={match.group(1)!r} ppt_agent={__version__!r}"
                )
        else:
            errors.append("pyproject.toml not found; cannot check version consistency")

    if IR_SCHEMA_VERSION not in SUPPORTED_IR_VERSIONS:
        errors.append(
            f"IR_SCHEMA_VERSION {IR_SCHEMA_VERSION!r} is not in SUPPORTED_IR_VERSIONS"
        )
    return errors


def build_manifest(root: str | Path, *, version: str | None = None) -> dict[str, Any]:
    from . import __version__

    base = Path(root).resolve()
    entries = [
        FileEntry(
            path=path.relative_to(base).as_posix(),
            sha256=file_digest(path),
            bytes=path.stat().st_size,
        )
        for path in iter_release_files(base)
    ]
    return {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "package_version": version or __version__,
        "core_api_version": CORE_API_VERSION,
        "ir_schema_version": IR_SCHEMA_VERSION,
        "adapter_protocol_version": ADAPTER_PROTOCOL_VERSION,
        "benchmark_schema_version": BENCHMARK_SCHEMA_VERSION,
        "supported_ir_versions": list(SUPPORTED_IR_VERSIONS),
        "file_count": len(entries),
        "total_bytes": sum(entry.bytes for entry in entries),
        "digest": aggregate_digest(entries),
        "files": [entry.to_dict() for entry in entries],
    }


def verify_manifest(root: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Compare the working tree against a manifest and report every difference."""
    base = Path(root).resolve()
    expected = {
        str(item["path"]): str(item["sha256"])
        for item in (manifest.get("files") or [])
        if isinstance(item, dict) and "path" in item and "sha256" in item
    }
    actual_entries = [
        FileEntry(
            path=path.relative_to(base).as_posix(),
            sha256=file_digest(path),
            bytes=path.stat().st_size,
        )
        for path in iter_release_files(base)
    ]
    actual = {entry.path: entry.sha256 for entry in actual_entries}

    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    changed = sorted(
        name for name in set(expected) & set(actual) if expected[name] != actual[name]
    )
    return {
        "ok": not (missing or extra or changed),
        "declared_digest": manifest.get("digest"),
        "actual_digest": aggregate_digest(actual_entries),
        "missing": missing,
        "changed": changed,
        "extra": extra,
        "counts": {
            "expected": len(expected),
            "actual": len(actual),
            "missing": len(missing),
            "changed": len(changed),
            "extra": len(extra),
        },
    }


def write_manifest(manifest: dict[str, Any], path: str | Path) -> Path:
    from .textio import write_json_lf

    return write_json_lf(path, manifest)


def read_manifest(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ppt-agent-release",
        description="Build or verify a deterministic PPT Agent release manifest",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="write a release manifest for the working tree")
    build.add_argument("--root", type=Path, default=Path.cwd())
    build.add_argument("-o", "--output", type=Path, default=Path("dist/release-manifest.json"))

    verify = sub.add_parser("verify", help="check the working tree against a manifest")
    verify.add_argument("--root", type=Path, default=Path.cwd())
    verify.add_argument("--manifest", type=Path, default=Path("dist/release-manifest.json"))

    check = sub.add_parser("check-version", help="verify version consistency across the repo")
    check.add_argument("--root", type=Path, default=Path.cwd())

    args = parser.parse_args(argv)

    if args.command == "build":
        errors = check_versions(args.root)
        if errors:
            for error in errors:
                print(f"version error: {error}")
            return 2
        manifest = build_manifest(args.root)
        target = write_manifest(manifest, args.output)
        print(f"wrote {target} ({manifest['file_count']} files, digest {manifest['digest'][:16]})")
        return 0

    if args.command == "verify":
        report = verify_manifest(args.root, read_manifest(args.manifest))
        for name in report["missing"]:
            print(f"missing: {name}")
        for name in report["changed"]:
            print(f"changed: {name}")
        for name in report["extra"]:
            print(f"unexpected: {name}")
        print(f"release verification: {'PASS' if report['ok'] else 'FAIL'} ({report['counts']})")
        return 0 if report["ok"] else 2

    errors = check_versions(args.root)
    for error in errors:
        print(f"version error: {error}")
    print(f"version consistency: {'PASS' if not errors else 'FAIL'}")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
