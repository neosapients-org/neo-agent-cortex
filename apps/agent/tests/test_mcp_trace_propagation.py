"""Why the platform call has to carry a traceparent.

`resolve_context` is not a dumb data fetch — the platform runs its OWN model to turn the
question into SQL. Those tokens are spent on the platform's side, and without a shared trace
id they land in a trace of their own, unconnected to the conversation that caused them.

The consequence is specific and misleading: this variant looks CHEAPER than it is, because
the dashboard only counts the model calls made inside this process. The whole experiment is a
cost comparison, so an invisible chunk of one side's cost is not a small problem.

ns_probe ships `get_injection_headers()`, but nothing called it — its httpx instrumentor does
not inject, and the MCP client sent only its API key and content headers.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "ns_probe"))

from ns_probe import configure, get_tracer  # noqa: E402

from app.mcp.client import MCPClient  # noqa: E402


def test_headers_carry_a_traceparent_inside_a_span():
    configure(service_name="agent-cortex", endpoint="http://127.0.0.1:9/v1/traces")
    client = MCPClient()

    with get_tracer("test").start_span("turn"):
        headers = client.headers

    # Assert on the key set, never the dict: these headers carry the platform API key,
    # and a failing `assert "x" in headers` prints every value.
    assert "traceparent" in set(headers), (
        "no traceparent — the platform's own model spend cannot be joined to this turn, "
        "so this variant under-reports its cost"
    )
    version, trace_id, span_id, flags = headers["traceparent"].split("-")
    assert version == "00"
    assert len(trace_id) == 32 and int(trace_id, 16) != 0
    assert len(span_id) == 16 and int(span_id, 16) != 0


def test_the_api_key_and_content_headers_are_still_sent():
    """Propagation must be additive — losing these breaks every platform call."""
    client = MCPClient()

    with get_tracer("test").start_span("turn"):
        headers = client.headers

    assert "X-API-Key" in set(headers)
    assert headers["Content-Type"] == "application/json"
    assert "text/event-stream" in headers["Accept"]


def test_headers_still_work_with_no_span_open():
    """Outside a turn there is nothing to propagate; that must not raise."""
    client = MCPClient()

    headers = client.headers

    assert "X-API-Key" in set(headers)
