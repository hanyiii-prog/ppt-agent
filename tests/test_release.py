import json
from pathlib import Path

from ppt_agent import __version__
from ppt_agent.contracts import RELEASE_SCHEMA_VERSION
from ppt_agent.release import (
    aggregate_digest,
    build_manifest,
    check_versions,
    file_digest,
    iter_release_files,
    main,
    read_manifest,
    verify_manifest,
    write_manifest,
)


def _tree(root: Path) -> Path:
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_core.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (root / "README.md").write_text("# Readme\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")
    # Noise that must never enter the manifest.
    (root / "src" / "pkg" / "__pycache__").mkdir(parents=True)
    (root / "src" / "pkg" / "__pycache__" / "core.cpython-313.pyc").write_bytes(b"\x00")
    (root / "src" / "pkg" / "pkg.egg-info").mkdir(parents=True)
    (root / "src" / "pkg" / "pkg.egg-info" / "PKG-INFO").write_text("x", encoding="utf-8")
    return root


def test_iter_release_files_skips_caches_and_sorts(tmp_path: Path):
    root = _tree(tmp_path)
    names = [path.relative_to(root).as_posix() for path in iter_release_files(root)]
    assert names == sorted(names)
    assert "src/pkg/core.py" in names
    assert "tests/test_core.py" in names
    assert "README.md" in names
    assert "pyproject.toml" in names
    assert not any("__pycache__" in name for name in names)
    assert not any(name.endswith(".pyc") for name in names)
    assert not any("egg-info" in name for name in names)


def test_manifest_has_the_declared_contract_versions(tmp_path: Path):
    manifest = build_manifest(_tree(tmp_path))
    assert manifest["schema_version"] == RELEASE_SCHEMA_VERSION
    assert manifest["package_version"] == __version__
    assert manifest["core_api_version"] == "1.0"
    assert manifest["ir_schema_version"] == "1.0"
    assert manifest["file_count"] == len(manifest["files"])
    assert manifest["total_bytes"] == sum(item["bytes"] for item in manifest["files"])
    assert len(manifest["digest"]) == 64


def test_manifest_is_reproducible_across_rebuilds(tmp_path: Path):
    first = build_manifest(_tree(tmp_path))
    second = build_manifest(tmp_path)
    assert first["digest"] == second["digest"]
    assert first == second


def test_file_digest_is_content_addressed(tmp_path: Path):
    path = tmp_path / "a.txt"
    path.write_text("hello", encoding="utf-8")
    assert file_digest(path) == file_digest(path)
    other = tmp_path / "b.txt"
    other.write_text("hellp", encoding="utf-8")
    assert file_digest(path) != file_digest(other)


def test_aggregate_digest_tracks_the_ordered_file_list():
    from ppt_agent.release import FileEntry

    assert aggregate_digest([FileEntry("a", "1", 1), FileEntry("b", "2", 1)]) != aggregate_digest(
        [FileEntry("b", "2", 1), FileEntry("a", "1", 1)]
    )


def test_verify_passes_on_an_untouched_tree(tmp_path: Path):
    root = _tree(tmp_path)
    manifest = write_manifest(build_manifest(root), tmp_path / "manifest.json")
    report = verify_manifest(root, read_manifest(manifest))
    assert report["ok"] is True
    assert report["counts"] == {"expected": 5, "actual": 5, "missing": 0, "changed": 0, "extra": 0}
    assert report["declared_digest"] == report["actual_digest"]


def test_verify_detects_changed_missing_and_extra_files(tmp_path: Path):
    root = _tree(tmp_path)
    manifest = build_manifest(root)

    (root / "src" / "pkg" / "core.py").write_text("VALUE = 2\n", encoding="utf-8")
    report = verify_manifest(root, manifest)
    assert report["ok"] is False
    assert report["changed"] == ["src/pkg/core.py"]

    (root / "docs" / "guide.md").unlink()
    report = verify_manifest(root, manifest)
    assert report["missing"] == ["docs/guide.md"]

    (root / "docs" / "new.md").write_text("# New\n", encoding="utf-8")
    report = verify_manifest(root, manifest)
    assert report["extra"] == ["docs/new.md"]
    assert report["declared_digest"] != report["actual_digest"]


def test_check_versions_flags_a_pyproject_mismatch(tmp_path: Path):
    root = _tree(tmp_path)
    assert check_versions(root) == []

    (root / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
    errors = check_versions(root)
    assert any("version mismatch" in error for error in errors)


def test_check_versions_requires_a_pyproject(tmp_path: Path):
    root = _tree(tmp_path)
    (root / "pyproject.toml").unlink()
    assert any("pyproject.toml not found" in error for error in check_versions(root))


def test_release_cli_build_and_verify(tmp_path: Path, capsys):
    root = _tree(tmp_path)
    output = tmp_path / "dist" / "release-manifest.json"
    assert main(["build", "--root", str(root), "-o", str(output)]) == 0
    assert "wrote" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["file_count"] == 5

    assert main(["verify", "--root", str(root), "--manifest", str(output)]) == 0
    assert "PASS" in capsys.readouterr().out

    (root / "src" / "pkg" / "core.py").write_text("VALUE = 3\n", encoding="utf-8")
    assert main(["verify", "--root", str(root), "--manifest", str(output)]) == 2
    captured = capsys.readouterr().out
    assert "changed: src/pkg/core.py" in captured
    assert "FAIL" in captured


def test_release_cli_blocks_on_a_version_mismatch(tmp_path: Path, capsys):
    root = _tree(tmp_path)
    (root / "pyproject.toml").write_text('[project]\nversion = "0.0.1"\n', encoding="utf-8")
    assert main(["build", "--root", str(root), "-o", str(tmp_path / "m.json")]) == 2
    assert "version error" in capsys.readouterr().out


def test_release_cli_check_version(tmp_path: Path, capsys):
    root = _tree(tmp_path)
    assert main(["check-version", "--root", str(root)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_repository_manifest_verifies_against_itself(repo_root: Path):
    """The shipped tree must be self-consistent, caches excluded."""
    manifest = build_manifest(repo_root)
    assert manifest["file_count"] > 20
    report = verify_manifest(repo_root, manifest)
    assert report["ok"] is True, report
