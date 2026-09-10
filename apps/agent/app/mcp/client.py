"""MCP client for tool discovery and execution."""

import time
import logging
import httpx
from ..config import config

logger = logging.getLogger(__name__)


def _parse_sse_body(text: str) -> dict | None:
    """Extract the JSON-RPC payload from an SSE (text/event-stream) response body.

    Returns the parsed dict, or None if the body is not parseable SSE JSON.
    """
    if not text or "data:" not in text:
        return None
    import json as _json
    last = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            chunk = line[len("data:"):].strip()
            if not chunk or chunk == "[DONE]":
                continue
            try:
                last = _json.loads(chunk)
            except _json.JSONDecodeError:
                continue
    return last


class MCPClient:
    """Client for Neo Platform MCP server."""

    def __init__(self):
        self.url = config.mcp_url
        self.api_key = config.mcp_api_key
        self._tools: list[dict] | None = None

    @property
    def headers(self) -> dict:
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            # The MCP server streams progress over SSE — without advertising that we
            # accept text/event-stream it can hang until the gateway times out (504).
            "Accept": "application/json, text/event-stream",
        }
        # W3C trace context, so the platform's server-side spans become part of THIS
        # turn's trace. resolve_context runs the platform's own model to build its SQL;
        # without this the tokens it spends land in an unrelated trace and this variant
        # reads as cheaper than it is. ns_probe shipped the helper but nothing called it.
        # Best-effort: a tracing failure must never break a data call.
        try:
            from ns_probe import get_injection_headers

            headers.update(get_injection_headers())
        except Exception:
            pass
        return headers

    async def list_tools(self) -> list[dict]:
        """Discover available tools from the MCP server."""
        if self._tools is not None:
            return self._tools

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self.url,
                headers=self.headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {},
                },
            )
            response.raise_for_status()
            data = response.json()
            self._tools = data.get("result", {}).get("tools", [])
            return self._tools

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Execute a tool on the MCP server, recording the call for the UI's
        "queries sent to the platform" panel. Every call (including retries and
        sub-questions) flows through here, so this is the single capture point."""
        result = await self._call_tool_impl(tool_name, arguments)
        try:
            from ..graph.nodes.stream_channel import record_platform_call
            record_platform_call({
                "tool": result.get("tool", tool_name),
                "q": (arguments or {}).get("query"),
                "ok": bool(result.get("success")),
                "ms": result.get("latency_ms"),
            })
        except Exception:
            pass
        return result

    async def _call_tool_impl(self, tool_name: str, arguments: dict) -> dict:
        """Execute a tool on the MCP server.

        The resolve_context backend can be slow to warm up and occasionally times
        out at the gateway. We retry transient timeouts a couple of times before
        giving up, and always return a structured dict (never raise) so the graph
        can surface a clean message.
        """
        start = time.perf_counter()
        max_attempts = 2
        _GATEWAY_STATUSES = {502, 503, 504}

        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        response = None
        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    response = await client.post(
                        self.url,
                        headers=self.headers,
                        json=payload,
                    )
                # Retry transient gateway errors (server warming up / overloaded)
                if response.status_code in _GATEWAY_STATUSES and attempt < max_attempts:
                    logger.warning(
                        "[MCP] Gateway %s | tool=%s | attempt=%s/%s — retrying",
                        response.status_code, tool_name, attempt, max_attempts,
                    )
                    response = None
                    continue
                break
            except httpx.TimeoutException:
                logger.warning(
                    "[MCP] Timeout calling tool | tool=%s | attempt=%s/%s",
                    tool_name, attempt, max_attempts,
                )
                response = None
                continue

        latency_ms = round((time.perf_counter() - start) * 1000)

        if response is None:
            # Every attempt timed out / 5xx'd — the MCP server is unresponsive/overloaded.
            logger.error(
                "[MCP] Tool call failed after %s attempts | tool=%s | latency=%sms",
                max_attempts, tool_name, latency_ms,
            )
            return {
                "tool": tool_name,
                "args": arguments,
                "response": {},
                "latency_ms": latency_ms,
                "success": False,
                "error": (
                    "The agent data service did not respond in time (gateway timeout) "
                    "after multiple attempts. The data platform is currently slow or "
                    "unavailable — please try again shortly."
                ),
            }

        if True:

            # Try to parse JSON body even on error status codes
            try:
                data = response.json()
            except Exception:
                # The server may stream the result as SSE (text/event-stream):
                #   event: message\n data: {json}\n\n
                # Recover the final JSON-RPC payload from the last `data:` line.
                sse_data = _parse_sse_body(response.text)
                if sse_data is not None:
                    data = sse_data
                elif not response.is_success:
                    logger.error(
                        "[MCP] Tool call failed | tool=%s | status=%s | url=%s | response=%s",
                        tool_name,
                        response.status_code,
                        str(response.url),
                        response.text[:500],
                    )
                    return {
                        "tool": tool_name,
                        "args": arguments,
                        "response": {},
                        "latency_ms": latency_ms,
                        "success": False,
                        "error": f"HTTP {response.status_code}: {response.text[:200]}",
                    }
                else:
                    data = {}

            # Handle JSON-RPC error responses (even on HTTP 200 or 500)
            if "error" in data:
                error_msg = data["error"].get("message", "Unknown error")
                logger.warning(
                    "[MCP] Tool returned error | tool=%s | status=%s | error=%s",
                    tool_name,
                    response.status_code,
                    error_msg[:300],
                )
                return {
                    "tool": tool_name,
                    "args": arguments,
                    "response": {},
                    "latency_ms": latency_ms,
                    "success": False,
                    "error": error_msg,
                }

            if not response.is_success:
                logger.error(
                    "[MCP] Tool call failed | tool=%s | status=%s | url=%s",
                    tool_name,
                    response.status_code,
                    str(response.url),
                )
                return {
                    "tool": tool_name,
                    "args": arguments,
                    "response": {},
                    "latency_ms": latency_ms,
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                }

        result = data.get("result", {})

        return {
            "tool": tool_name,
            "args": arguments,
            "response": result,
            "latency_ms": latency_ms,
            "success": True,
        }


# Singleton
mcp_client = MCPClient()
