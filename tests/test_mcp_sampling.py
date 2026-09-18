"""End-to-end stdio tests for the sampling-enabled server (batch 3).

The full client script is written up-front: `initialize` -> `notifications/
initialized` -> `tools/call` -> the pre-scripted sampling *response* (when
the scenario has one). Because the server processes stdin in order, the
response line arrives exactly while the tool handler is suspended inside
``sampling/createMessage`` -- the real interleaving, without a second thread.

The first sampling request of a session always carries id ``-1`` (negative
namespace, no collision with inbound request ids), so responses can be
pre-scripted.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from ppt_agent.mcp.server import serve

MARKDOWN = """# 上线总结

## 项目概况

- 覆盖 5 个院区

## 项目成效

- 四甲评审通过
"""

SAMPLING_REQUEST_ID = -1

INIT_WITH_SAMPLING = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2025-06-18",
                                 "capabilities": {"sampling": {}}}}
INIT_PLAIN = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {}}}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def _call_narrative(request_id: int = 2) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": {"name": "ppt_agent_narrative_plan",
                       "arguments": {"markdown": MARKDOWN}}}


def _sampling_response(request_id: int, text: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id,
            "result": {"content": {"type": "text", "text": text}}}


def _run(lines: list, workspace: Path, *, sampling_timeout_s: float = 5.0) -> list[dict]:
    stdin = io.StringIO("\n".join(json.dumps(item, ensure_ascii=False) for item in lines) + "\n")
    stdout = io.StringIO()
    code = serve(stdin, stdout, workspace=workspace, log=io.StringIO(),
                 sampling_timeout_s=sampling_timeout_s)
    assert code == 0
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


def _tool_payload(response: dict) -> dict:
    return json.loads(response["result"]["content"][0]["text"])


def _assert_sampling_request_emitted(outputs: list[dict]) -> None:
    requests = [output for output in outputs if output.get("method") == "sampling/createMessage"]
    assert requests and requests[0]["id"] == SAMPLING_REQUEST_ID


def test_sampling_capable_host_gets_model_planned_narrative(workspace: Path) -> None:
    lines: list = [
        INIT_WITH_SAMPLING,
        INITIALIZED,
        _call_narrative(),
        # the fake host model reorders the arc; scripted ahead of time (id=-1)
        _sampling_response(SAMPLING_REQUEST_ID, "- 项目成效\n- 项目概况"),
    ]
    outputs = _run(lines, workspace)
    _assert_sampling_request_emitted(outputs)
    narrative = _tool_payload(outputs[-1])
    assert narrative["metadata"]["llm"] == "sampled"
    # the model ordered two sections; the H1 title (cover material) trails
    assert narrative["arc"] == ["项目成效", "项目概况", "上线总结"]


def test_host_without_sampling_runs_rules_and_discloses_off(workspace: Path) -> None:
    outputs = _run([INIT_PLAIN, INITIALIZED, _call_narrative()], workspace)
    narrative = _tool_payload(outputs[-1])
    assert narrative["metadata"]["llm"] == "off"
    assert narrative["mode"] == "rules"
    assert narrative["arc"], "rules floor must still produce the arc"
    assert not [output for output in outputs if output.get("method") == "sampling/createMessage"], (
        "hosts without sampling must never be asked"
    )


def test_sampling_timeout_falls_back_and_discloses(workspace: Path) -> None:
    # sampling declared but the host goes silent: no response is scripted
    outputs = _run([INIT_WITH_SAMPLING, INITIALIZED, _call_narrative()], workspace,
                   sampling_timeout_s=0.2)
    narrative = _tool_payload(outputs[-1])
    assert narrative["metadata"]["llm"] == "fallback"
    assert narrative["mode"] == "rules"
    assert narrative["arc"]


def test_sampling_error_response_falls_back_and_discloses(workspace: Path) -> None:
    lines: list = [
        INIT_WITH_SAMPLING,
        INITIALIZED,
        _call_narrative(),
        {"jsonrpc": "2.0", "id": SAMPLING_REQUEST_ID,
         "error": {"code": -32603, "message": "model exploded"}},
    ]
    outputs = _run(lines, workspace, sampling_timeout_s=2.0)
    narrative = _tool_payload(outputs[-1])
    assert narrative["metadata"]["llm"] == "fallback"
    assert narrative["mode"] == "rules"
    assert narrative["arc"]
