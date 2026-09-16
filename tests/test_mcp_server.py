import io
import json
from pathlib import Path

import pytest

from ppt_agent.mcp import (
    DEFAULT_PROTOCOL_VERSION,
    JsonRpcError,
    SERVER_NAME,
    ToolContext,
    ToolError,
    build_agent,
    call_tool,
    list_tools,
    parse_message,
    serve,
    tool_names,
)
from ppt_agent.mcp.protocol import INVALID_PARAMS, INVALID_REQUEST, METHOD_NOT_FOUND, PARSE_ERROR

EXPECTED_TOOLS = {
    "ppt_agent_capabilities",
    "ppt_agent_analyze_pptx",
    "ppt_agent_markdown_to_ir",
    "ppt_agent_ir_to_pptx",
    "ppt_agent_render_html",
    "ppt_agent_validate_ir",
    "ppt_agent_validate_pptx",
    "ppt_agent_audit_facts",
    "ppt_agent_build",
    "ppt_agent_host_profile",
}


def _run(lines: list, workspace: Path) -> list[dict]:
    stdin = io.StringIO(
        "\n".join(json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else item for item in lines) + "\n"
    )
    stdout = io.StringIO()
    assert serve(stdin, stdout, workspace=workspace, log=io.StringIO()) == 0
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


def _payload(response: dict) -> dict:
    return json.loads(response["result"]["content"][0]["text"])


# --- protocol -------------------------------------------------------------
def test_parse_message_validates_the_envelope():
    assert parse_message('{"jsonrpc": "2.0", "id": 1, "method": "ping"}')["method"] == "ping"
    with pytest.raises(JsonRpcError) as bad_json:
        parse_message("not json")
    assert bad_json.value.code == PARSE_ERROR
    with pytest.raises(JsonRpcError) as bad_version:
        parse_message('{"jsonrpc": "1.0", "id": 1, "method": "ping"}')
    assert bad_version.value.code == INVALID_REQUEST
    with pytest.raises(JsonRpcError) as bad_method:
        parse_message('{"jsonrpc": "2.0", "id": 1}')
    assert bad_method.value.code == INVALID_REQUEST


def test_tools_list_is_complete_and_schema_driven():
    assert set(tool_names()) == EXPECTED_TOOLS
    for spec in list_tools():
        assert spec["description"]
        assert spec["inputSchema"]["type"] == "object"
        assert spec["inputSchema"]["additionalProperties"] is False


def test_initialize_negotiates_a_known_protocol_version(workspace: Path):
    responses = _run([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}},
    ], workspace)
    assert responses[0]["result"]["protocolVersion"] == "2025-06-18"
    assert responses[1]["result"]["protocolVersion"] == DEFAULT_PROTOCOL_VERSION
    assert responses[0]["result"]["serverInfo"]["name"] == SERVER_NAME
    assert responses[0]["result"]["capabilities"]["tools"]["listChanged"] is False
    assert "PPT Agent" in responses[0]["result"]["instructions"]


def test_notifications_are_never_answered(workspace: Path):
    responses = _run([
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}},
        {"jsonrpc": "2.0", "id": 9, "method": "ping"},
    ], workspace)
    assert len(responses) == 1
    assert responses[0]["id"] == 9 and responses[0]["result"] == {}


def test_unknown_method_and_tool_produce_rpc_errors(workspace: Path):
    responses = _run([
        {"jsonrpc": "2.0", "id": 1, "method": "deck/teleport"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"arguments": {}}},
    ], workspace)
    assert responses[0]["error"]["code"] == METHOD_NOT_FOUND
    assert responses[1]["error"]["code"] == INVALID_PARAMS
    assert responses[2]["error"]["code"] == INVALID_PARAMS


def test_broken_json_is_reported_with_a_null_id(workspace: Path):
    responses = _run(["{oops"], workspace)
    assert len(responses) == 1
    assert responses[0]["id"] is None
    assert responses[0]["error"]["code"] == PARSE_ERROR


def test_empty_resource_and_prompt_listings(workspace: Path):
    responses = _run([
        {"jsonrpc": "2.0", "id": 1, "method": "resources/list"},
        {"jsonrpc": "2.0", "id": 2, "method": "resources/templates/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "prompts/list"},
    ], workspace)
    assert responses[0]["result"] == {"resources": []}
    assert responses[1]["result"] == {"resourceTemplates": []}
    assert responses[2]["result"] == {"prompts": []}


# --- tools ----------------------------------------------------------------
def test_capabilities_tool_reports_the_contract(workspace: Path):
    responses = _run([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "ppt_agent_capabilities", "arguments": {}}},
    ], workspace)
    body = _payload(responses[0])
    assert responses[0]["result"]["isError"] is False
    assert body["core_api_version"] == "1.0"
    assert body["negotiation"]["ok"] is True
    assert body["host_profiles"]


def test_markdown_to_ir_tool_accepts_inline_text(workspace: Path, sample_markdown: str):
    responses = _run([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "ppt_agent_markdown_to_ir",
                    "arguments": {"markdown": sample_markdown, "title": "汇报", "output": "ir/deck.json"}}},
    ], workspace)
    body = _payload(responses[0])
    assert body["slide_count"] == 4
    assert body["qa"]["passed"] is True
    assert Path(body["ir_path"]).exists()
    assert body["ir"]["ir_version"] == "1.0"


def test_markdown_to_ir_tool_reads_a_source_file(workspace: Path, sample_markdown: str):
    source = workspace / "source.md"
    source.write_text(sample_markdown, encoding="utf-8")
    responses = _run([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "ppt_agent_markdown_to_ir", "arguments": {"source": "source.md", "mode": "flat"}}},
    ], workspace)
    body = _payload(responses[0])
    assert body["mode"] == "flat" and body["slide_count"] == 4


def test_build_tool_writes_artifacts_inside_the_workspace(workspace: Path, sample_markdown: str):
    responses = _run([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "ppt_agent_build",
                    "arguments": {"markdown": sample_markdown, "out_dir": "deck", "stem": "demo", "gate": True}}},
    ], workspace)
    body = _payload(responses[0])
    assert body["ok"] is True
    assert body["renderer"] == "native-pptx"
    assert body["gate"]["passed"] is True
    assert len(body["manifest"]["pages"]) == 4
    for key in ("ir_path", "pptx_path", "html_path"):
        assert Path(body[key]).exists(), key
        assert Path(body[key]).resolve().is_relative_to(workspace.resolve()), key


def test_build_tool_refuses_to_escape_the_workspace(workspace: Path, sample_markdown: str):
    responses = _run([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "ppt_agent_build", "arguments": {"markdown": sample_markdown, "out_dir": "../../escape"}}},
    ], workspace)
    assert responses[0]["result"]["isError"] is True
    assert "escapes the workspace" in _payload(responses[0])["error"]


def test_missing_arguments_are_reported_as_tool_errors(workspace: Path):
    responses = _run([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "ppt_agent_build", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "ppt_agent_audit_facts", "arguments": {}}},
    ], workspace)
    assert responses[0]["result"]["isError"] is True
    assert "out_dir" in _payload(responses[0])["error"]
    assert responses[1]["result"]["isError"] is True


def test_validate_pptx_tool_reports_the_gate_mode(workspace: Path, sample_markdown: str):
    context = ToolContext(agent=build_agent(), workspace=workspace)
    build = call_tool("ppt_agent_build", {"markdown": sample_markdown, "out_dir": "deck", "stem": "d"}, context)
    pptx = json.loads(build["content"][0]["text"])["pptx_path"]
    result = call_tool(
        "ppt_agent_validate_pptx",
        {"pptx": str(Path(pptx).relative_to(workspace)), "output": "qa/report.json"},
        context,
    )
    body = json.loads(result["content"][0]["text"])
    assert body["mode"] in {"rendered", "structural"}
    assert body["passed"] is True
    assert Path(body["report_path"]).exists()


def test_audit_facts_tool_flags_unsupported_claims(workspace: Path, sample_markdown: str):
    context = ToolContext(agent=build_agent(), workspace=workspace)
    ir = json.loads(
        call_tool("ppt_agent_markdown_to_ir", {"markdown": sample_markdown}, context)["content"][0]["text"]
    )["ir"]
    result = call_tool(
        "ppt_agent_audit_facts",
        {"ir": ir, "facts": [{"claim": "不存在的说法", "source_id": "nowhere"}]},
        context,
    )
    body = json.loads(result["content"][0]["text"])
    assert body["passed"] is False and body["unsupported"] > 0


def test_host_profile_tool_negotiates(workspace: Path):
    context = ToolContext(agent=build_agent(), workspace=workspace)
    result = call_tool(
        "ppt_agent_host_profile",
        {"host": "workbuddy", "required": ["render_preview"]},
        context,
    )
    body = json.loads(result["content"][0]["text"])
    assert body["adapter"]["name"] == "workbuddy"
    assert body["negotiation"]["ok"] is True

    missing = call_tool("ppt_agent_host_profile", {"host": "unknown-host"}, context)
    assert missing["isError"] is True


def test_render_html_tool_and_validate_ir_tool(workspace: Path, sample_markdown: str):
    context = ToolContext(agent=build_agent(), workspace=workspace)
    ir = json.loads(
        call_tool("ppt_agent_markdown_to_ir", {"markdown": sample_markdown}, context)["content"][0]["text"]
    )["ir"]
    html = json.loads(
        call_tool("ppt_agent_render_html", {"ir": ir, "output": "preview/deck.html"}, context)["content"][0]["text"]
    )
    assert Path(html["path"]).exists()
    assert "class=\"slide\"" in Path(html["path"]).read_text(encoding="utf-8")

    report = json.loads(call_tool("ppt_agent_validate_ir", {"ir": ir}, context)["content"][0]["text"])
    assert report["passed"] is True


def test_context_rejects_input_paths_that_do_not_exist(workspace: Path):
    context = ToolContext(agent=build_agent(), workspace=workspace)
    with pytest.raises(ToolError) as exc:
        context.input_path("nope.md")
    assert "does not exist" in str(exc.value)
