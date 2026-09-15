from pathlib import Path

from ppt_agent.visual_regression import _prepare_output_dir


def test_prepare_output_dir_removes_stale_slide_files(tmp_path: Path):
    output = tmp_path / "rendered"
    output.mkdir()
    (output / "slide-1.png").write_bytes(b"old")
    (output / "slide-2.png").write_bytes(b"old")
    (output / "nested").mkdir()
    (output / "nested" / "stale.txt").write_text("old")
    _prepare_output_dir(output)
    assert list(output.iterdir()) == []
