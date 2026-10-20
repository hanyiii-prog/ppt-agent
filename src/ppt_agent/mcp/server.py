"""Dependency-free MCP stdio server.

Implements the subset of the Model Context Protocol a tool host needs:
`initialize`, `tools/list`, `tools/call`, `ping` and the empty resource/prompt
listings. JSON-RPC messages are newline-delimited; stdout carries protocol
traffic only, all diagnostics go to stderr.

Since the V2.1 LLM infrastructure (batch 3) the loop is *bidirectional*: a
tool handler can suspend itself and issue ``sampling/createMessage`` to the
host through ``SamplingSession``; inbound responses are routed back by id
while the handler waits. Hosts without the sampling capability are detected
at the ``initialize`` handshake and every consumer degrades -- and discloses
-- accordingly.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import queue
import sys
import threading
from pathlib import Path
from typing import Any, TextIO

from .. import __version__
from ..adapters import create_adapter
from ..contracts import MCP_PROTOCOL_VERSIONS
from ..llm.provider import (
    LLMUnavailableError,
    sampling_supported,
    sampling_vision_supported,
)
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
from .sampling import SamplingSession
from .tools import ToolContext, call_tool, list_tools

SERVER_NAME = "ppt-agent"
DEFAULT_PROTOCOL_VERSION = MCP_PROTOCOL_VERSIONS[0]

INSTRUCTIONS = (
    "PPT Agent builds presentations like software. Inspect sources and reference decks "
    "before proposing slides, keep Universal IR as the source of truth, always render the "
    "complete deck and gate every page before delivery, and never invent metrics, dates or "
    "conclusions. Call ppt_agent_capabilities first to learn which gates the host can run; "
    "a missing rasteriser degrades visual checks to structural geometry checks rather than "
    "removing them. To enable model review of rendered slides, the host must explicitly "
    "declare capabilities.experimental['ppt-agent'].samplingVision=true as well as sampling "
    "support during initialize; absent or false means screenshots are not sent to the model "
    "and deterministic checks are used with a warning. For long-running tools, pass "
    "params._meta.progressToken and surface every notifications/progress message to the user; "
    "do not wait until the final tool result to report progress. Direct Responses-compatible "
    "providers can be configured with PPT_AGENT_API_BASE_URL, PPT_AGENT_API_KEY, "
    "PPT_AGENT_MODEL, and optionally PPT_AGENT_VISION_MODEL. A PPTX/HTML/PDF reference "
    "is consumed only through ppt_agent_generate; image-based PDF pages are sent only "
    "when vision support is explicitly configured."
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
        client_capabilities = params.get("capabilities")
        if context.session is not None:
            capabilities = client_capabilities if isinstance(client_capabilities, dict) else None
            context.session.supported = sampling_supported(
                capabilities
            )
            context.session.vision_supported = sampling_vision_supported(capabilities)
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
        call_context = context
        meta = params.get("_meta")
        progress_token = meta.get("progressToken") if isinstance(meta, dict) else None
        if progress_token is not None and context.notify is not None:
            sequence = 0

            def emit_progress(event: dict[str, Any]) -> None:
                nonlocal sequence
                sequence += 1
                detail = event.get("detail") or {}
                extras = " ".join(
                    f"{key}={value}"
                    for key, value in detail.items()
                    if value not in (None, "")
                )
                message = str(event.get("message") or event.get("stage") or "进行中")
                if extras:
                    message += f" ({extras})"
                context.notify({
                    "jsonrpc": "2.0",
                    "method": "notifications/progress",
                    "params": {
                        "progressToken": progress_token,
                        "progress": sequence,
                        "message": message,
                    },
                })

            call_context = replace(context, progress_callback=emit_progress)
        return success(request_id, call_tool(name, params.get("arguments"), call_context))
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
    sampling_timeout_s: float = 60.0,
    sampling_retries: int = 1,
) -> int:
    """Run the stdio loop until the input stream closes.

    Inbound traffic is read by a daemon thread into a queue so a tool handler
    can suspend on ``sampling/createMessage`` without deadlocking the reader:
    while the handler waits for its response, the same queue keeps feeding
    the loop, and responses matching a pending sampling id are routed to the
    waiter instead of being dispatched as requests. On EOF the sentinel is
    re-queued rather than consumed, so the main loop's blocking get is always
    woken no matter which pump saw it first.
    """
    input_stream = stdin if stdin is not None else sys.stdin
    output_stream = stdout if stdout is not None else sys.stdout
    error_stream = log if log is not None else sys.stderr

    inbound: queue.Queue = queue.Queue()
    sentinel = object()

    def reader() -> None:
        try:
            for raw in input_stream:
                inbound.put(raw)
        finally:
            inbound.put(sentinel)

    def pump(timeout: float) -> None:
        """Block up to `timeout` for one inbound item and process it.

        On EOF the sentinel is *re-queued* (so the main loop's blocking get
        is always woken) and ``LLMUnavailableError`` signals closure.
        """
        item = inbound.get(timeout=timeout)
        if item is sentinel:
            inbound.put(sentinel)
            raise LLMUnavailableError("host_closed_input")
        if isinstance(item, str):
            dispatch(item)

    def dispatch(raw: str) -> None:
        line = raw.strip()
        if not line:
            return
        # a client *response* (no method) may belong to a pending sampling
        # request; route it before parse_message rejects it as malformed
        pre: dict[str, Any] | None = None
        try:
            candidate = json.loads(line)
            if isinstance(candidate, dict) and "method" not in candidate:
                pre = candidate
        except json.JSONDecodeError:
            pre = None
        if pre is not None and session.deliver_if_pending(pre):
            return
        try:
            message = parse_message(line)
        except JsonRpcError as exc:
            _write(output_stream, failure(None, exc.code, exc.message, exc.data))
            return
        try:
            response = handle_message(message, context=context)
        except JsonRpcError as exc:
            response = failure(message.get("id"), exc.code, exc.message, exc.data)
        except Exception as exc:  # noqa: BLE001 - a crash must not kill the session
            print(f"{SERVER_NAME} mcp: {type(exc).__name__}: {exc}", file=error_stream)
            response = failure(message.get("id"), INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
        if response is not None and not is_notification(message):
            _write(output_stream, response)

    session = SamplingSession(
        lambda payload: _write(output_stream, payload),
        pump_fn=pump,
        timeout_s=sampling_timeout_s,
        retries=sampling_retries,
    )
    context = ToolContext(
        agent=build_agent(host),
        workspace=Path(workspace or Path.cwd()),
        session=session,
        notify=lambda payload: _write(output_stream, payload),
    )
    threading.Thread(target=reader, daemon=True).start()

    while True:
        try:
            pump(3600.0)
        except queue.Empty:
            continue
        except LLMUnavailableError:
            break  # input stream closed (sentinel re-queued: always wakes us)
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
