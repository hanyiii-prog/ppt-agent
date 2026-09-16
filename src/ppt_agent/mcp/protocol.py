"""Minimal, dependency-free JSON-RPC 2.0 helpers for the MCP stdio transport."""
from __future__ import annotations

import json
from typing import Any

JSONRPC_VERSION = "2.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class JsonRpcError(Exception):
    """A JSON-RPC level failure, as opposed to a tool level failure."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            payload["data"] = self.data
        return payload


def success(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def failure(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": JsonRpcError(code, message, data).to_dict()}


def parse_message(line: str) -> dict[str, Any]:
    """Parse one newline-delimited JSON-RPC message."""
    try:
        message = json.loads(line)
    except json.JSONDecodeError as exc:
        raise JsonRpcError(PARSE_ERROR, f"invalid JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise JsonRpcError(INVALID_REQUEST, "message must be a JSON object")
    if message.get("jsonrpc") != JSONRPC_VERSION:
        raise JsonRpcError(INVALID_REQUEST, "jsonrpc must be \"2.0\"")
    if "method" not in message or not isinstance(message["method"], str):
        raise JsonRpcError(INVALID_REQUEST, "method must be a string")
    return message


def is_notification(message: dict[str, Any]) -> bool:
    """Notifications carry no id and must never be answered."""
    return "id" not in message
