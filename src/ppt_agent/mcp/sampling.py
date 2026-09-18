"""Sampling session: the server-side half of ``sampling/createMessage``.

The MCP stdio server is a single logical loop; a tool handler that needs the
host model must be able to *suspend itself*, write a JSON-RPC request onto
stdout, and resume when the matching response arrives on stdin -- possibly
after other traffic. Three pieces make that work:

* a daemon **reader thread** owned by ``server.serve`` pushes raw lines into
  a queue (so waits can carry a timeout),
* a **pump callback** -- while a handler is suspended, ``create_message``
  drives the inbound queue itself through ``pump_fn``; the serve loop hands
  every parsed message to ``deliver_if_pending`` first, so responses
  matching an outstanding sampling id are routed to their waiter,
* ``create_message`` -- writes the request (negative ids, never colliding
  with inbound request ids), pumps until the matching response, a timeout,
  or the retry budget is exhausted.

Every failure surfaces as ``LLMUnavailableError`` so consumers can degrade
and disclose (red line 6). No LLM logic lives here -- transport only.
"""

from __future__ import annotations

import queue
import time
from typing import Any, Callable

from ..llm.provider import LLMUnavailableError


class SamplingSession:
    """One server session's sampling state (writer + pump + pending routing)."""

    def __init__(
        self,
        write_fn: Callable[[dict[str, Any]], None],
        *,
        pump_fn: Callable[[float], None] | None = None,
        timeout_s: float = 60.0,
        retries: int = 1,
    ) -> None:
        self.write_fn = write_fn
        # pump_fn(timeout) must block up to `timeout` for one inbound message
        # and dispatch it (serve owns that). It raises queue.Empty on timeout
        # and LLMUnavailableError when the input stream closes. Without a
        # pump there is no way to receive a response while suspended.
        self.pump_fn = pump_fn
        self.timeout_s = float(timeout_s)
        self.retries = int(retries)
        self.supported = False          # set from the client initialize handshake
        self._pending: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._id_counter = 0

    # ------------------------------------------------------------------ #
    # inbound routing (called from the serve loop / pump)
    # ------------------------------------------------------------------ #
    def deliver_if_pending(self, message: dict[str, Any]) -> bool:
        """Route a parsed inbound message to a pending sampler. True if consumed."""
        if message.get("method") is not None:
            return False
        key = str(message.get("id"))
        holder = self._pending.get(key)
        if holder is None:
            return False
        holder.put(message)
        return True

    # ------------------------------------------------------------------ #
    # outbound request (called from tool handlers)
    # ------------------------------------------------------------------ #
    def create_message(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send ``sampling/createMessage`` and wait for the matching response."""
        if not self.supported:
            raise LLMUnavailableError("host_without_sampling")
        if self.pump_fn is None:
            raise LLMUnavailableError("sampling_pump_unavailable")
        self._id_counter -= 1
        msg_id = self._id_counter
        payload = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "sampling/createMessage",
            "params": request,
        }
        last_error: LLMUnavailableError | None = None
        for _attempt in range(self.retries + 1):
            key = str(msg_id)
            holder: queue.Queue[dict[str, Any]] = queue.Queue()
            self._pending[key] = holder
            closed = False
            try:
                self.write_fn(payload)
                deadline = time.monotonic() + self.timeout_s
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        last_error = LLMUnavailableError("sampling_timeout")
                        break
                    try:
                        self.pump_fn(min(remaining, 0.5))
                    except queue.Empty:
                        continue
                    if not holder.empty():
                        message = holder.get()
                        break
            except LLMUnavailableError as exc:
                # input stream closed while waiting: retrying is pointless
                last_error = exc
                closed = True
            finally:
                self._pending.pop(key, None)
            if closed:
                break
            if last_error is not None:
                continue  # retry
            if "error" in message:
                error = message["error"] or {}
                last_error = LLMUnavailableError(
                    f"sampling_error: {error.get('message') or 'unknown'}"
                )
                continue
            return message.get("result") or {}
        raise last_error or LLMUnavailableError("sampling_unavailable")
