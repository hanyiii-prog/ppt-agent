"""MCP progress forwarding for long-running generation tool calls."""

from __future__ import annotations

import io
import json
from pathlib import Path

from ppt_agent.mcp.server import serve

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def _run(lines: list[dict], workspace: Path) -> list[dict]:
    stdin = io.StringIO(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in lines) + "\n"
    )
    stdout = io.StringIO()
    assert serve(stdin, stdout, workspace=workspace, log=io.StringIO()) == 0
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


def _generate_call(progress_token: str | None = None) -> dict:
    params: dict = {
        "name": "ppt_agent_generate",
        "arguments": {"markdown": "# 测试", "out_dir": "out"},
    }
    if progress_token is not None:
        params["_meta"] = {"progressToken": progress_token}
    return {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": params}


def test_generate_forwards_pipeline_events_as_mcp_progress(
    workspace: Path,
    monkeypatch,
) -> None:
    events = [
        {"stage": "start", "message": "开始生成演示文稿", "detail": {}},
        {
            "stage": "render_start",
            "message": "正在渲染模板路线页面",
            "detail": {"page_total": 20},
        },
    ]

    def fake_pipeline(markdown: str, **kwargs):
        callback = kwargs["progress_callback"]
        assert callable(callback)
        for event in events:
            callback(event)
        return {"ok": True}

    monkeypatch.setattr("ppt_agent.agent.pipeline.run_pipeline", fake_pipeline)
    outputs = _run(
        [INIT, INITIALIZED, _generate_call("progress-1")],
        workspace,
    )

    progress = [
        item for item in outputs
        if item.get("method") == "notifications/progress"
    ]
    assert [item["params"]["message"] for item in progress] == [
        "开始生成演示文稿",
        "正在渲染模板路线页面 (page_total=20)",
    ]
    assert [item["params"]["progress"] for item in progress] == [1, 2]
    assert all(
        item["params"]["progressToken"] == "progress-1"
        for item in progress
    )
    assert outputs[-1]["id"] == 2


def test_generate_does_not_emit_progress_without_a_token(
    workspace: Path,
    monkeypatch,
) -> None:
    def fake_pipeline(markdown: str, **kwargs):
        kwargs["progress_callback"]({
            "stage": "start",
            "message": "开始生成演示文稿",
            "detail": {},
        })
        return {"ok": True}

    monkeypatch.setattr("ppt_agent.agent.pipeline.run_pipeline", fake_pipeline)
    outputs = _run([INIT, INITIALIZED, _generate_call()], workspace)
    assert not [
        item for item in outputs
        if item.get("method") == "notifications/progress"
    ]
