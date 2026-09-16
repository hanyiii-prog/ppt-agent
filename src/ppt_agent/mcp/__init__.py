"""MCP (Model Context Protocol) server for PPT Agent.

Exposes the SDK as MCP tools over stdio so any MCP-capable host (Codex,
WorkBuddy, Claude, and others) can drive the pipeline without bespoke glue.
Zero third-party dependencies: the transport is plain newline-delimited
JSON-RPC 2.0 on stdin/stdout.
"""
from __future__ import annotations

from .protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    JSONRPC_VERSION,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    JsonRpcError,
    failure,
    parse_message,
    success,
)
from .server import (
    DEFAULT_PROTOCOL_VERSION,
    INSTRUCTIONS,
    SERVER_NAME,
    build_agent,
    handle_message,
    serve,
)
from .tools import (
    TOOL_IMPLEMENTATIONS,
    TOOL_SPECS,
    ToolContext,
    ToolError,
    call_tool,
    list_tools,
    tool_names,
)

__all__ = [
    "DEFAULT_PROTOCOL_VERSION",
    "INSTRUCTIONS",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "JSONRPC_VERSION",
    "JsonRpcError",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "SERVER_NAME",
    "TOOL_IMPLEMENTATIONS",
    "TOOL_SPECS",
    "ToolContext",
    "ToolError",
    "build_agent",
    "call_tool",
    "failure",
    "handle_message",
    "list_tools",
    "parse_message",
    "serve",
    "success",
    "tool_names",
]
