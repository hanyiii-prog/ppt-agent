"""Dependency-free MCP stdio server.

Implements the subset of the Model Context Protocol a tool host needs:
`initialize`, `tools/list`, `tools/call`, `ping` and the empty resource/prompt
listings. JSON-RPC messages are newline-delimited; stdout carries protocol
traffic only, all diagnostics go to stderr.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from .. import __version__
from ..adapters import create_adapter
from ..contracts import MCP_PROTOCOL_VERSIONS
from ..sdk import PptAgent
from .protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    JsonRpcError,
    METHOD_NOT_FOUND,
    failure,
    is_notification,
    parse_message,
    success,
)
from .tools import ToolContext, call_tool, list_tools

SERVER_NAME = "ppt-agent"
DEFAULT_PROTOCOL_VERSION = MCP_PROTOCOL_VERSIONS[0]

INSTRUCTIONS = (
    "PPT Agent builds presentations like software. Inspect sources and reference decks "
    "before proposing slides, keep Universal IR as the source of truth, always render the "
    "complete deck and gate every page before delivery, and never invent metrics, dates or "
    "conclusions. Call ppt_agent_capabilities first to learn which gates the host can run; "
    "a missing rasteriser degrades visual checks to structural geometry checks rather than "
    "removing them."
)


def build_agent(host: str | None = None) -> PptAgent:
    return PptAgent(create_adapter(host) if host else None)


def handle_message(
    message: dict[str, Any],
    *,
    context: ToolContext,
) -> dict[str, Any] | None:
    """Dispatch one JSON-RPC message. Returns None for notifications."""
    method = message["method"]
    params = message.get("params") or {}
    if not isinstance(params, dict):
        raise JsonRpcError(INVALID_PARAMS, "params must be an object")
    request_id = message.get("id")

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in MCP_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
        return success(request_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "instructions": INSTRUCTIONS,
        })
    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None
    if method == "ping":
        return success(request_id, {})
    if method == "tools/list":
        return success(request_id, {"tools": list_tools()})
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise JsonRpcError(INVALID_PARAMS, "tools/call requires a tool name")
        return success(request_id, call_tool(name, params.get("arguments"), context))
    if method == "resources/list":
        return success(request_id, {"resources": []})
    if method == "resources/templates/list":
        return success(request_id, {"resourceTemplates": []})
    if method == "prompts/list":
        return success(request_id, {"prompts": []})
    raise JsonRpcError(METHOD_NOT_FOUND, f"unknown method: {method}")


def _write(stream: TextIO, payload: dict[str, Any]) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
    stream.flush()


def serve(
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    *,
    workspace: str | Path | None = None,
    host: str | None = None,
    log: TextIO | None = None,
) -> int:
    """Run the stdio loop until the input stream closes."""
    input_stream = stdin if stdin is not None else sys.stdin
    output_stream = stdout if stdout is not None else sys.stdout
    error_stream = log if log is not None else sys.stderr
    context = ToolContext(agent=build_agent(host), workspace=Path(workspace or Path.cwd()))

    for raw in input_stream:
        line = raw.strip()
        if not line:
            continue
        try:
            message = parse_message(line)
        except JsonRpcError as exc:
            _write(output_stream, failure(None, exc.code, exc.message, exc.data))
            continue
        try:
            response = handle_message(message, context=context)
        except JsonRpcError as exc:
            response = failure(message.get("id"), exc.code, exc.message, exc.data)
        except Exception as exc:  # noqa: BLE001 - a crash must not kill the session
            print(f"{SERVER_NAME} mcp: {type(exc).__name__}: {exc}", file=error_stream)
            response = failure(message.get("id"), INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
        if response is not None and not is_notification(message):
            _write(output_stream, response)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ppt-agent-mcp",
        description="PPT Agent MCP server (stdio transport)",
    )
    parser.add_argument("--workspace", type=Path, default=None,
                        help="directory the server may write artifacts into (default: cwd)")
    parser.add_argument("--host", default=None,
                        help="host profile name: codex, workbuddy, doubao, claude, chatgpt")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    return serve(workspace=args.workspace, host=args.host)


if __name__ == "__main__":
    raise SystemExit(main())
