"""Per-turn accounting for the CORTEX PLATFORM's own model spend.

`app.llm` counts what this agent spends talking to the model provider. That is only
half of a Cortex turn: `resolve_context` runs the platform's own LLM (understand →
discovery → plan → synthesis) to build and execute its SQL, and that spend is
invisible here — the tokens are burnt in another process, against another account.

Until the gateway change in neo-platform#1164 ("feat(gateway): surface per-turn LLM
cost to MCP callers") the only record of it was the trace store: `app/mcp/client.py`
injects W3C trace headers so the platform's spans join this turn's trace, and the
totals had to be read back out of ClickHouse behind workspace auth. That is why the
comparison doc's "CX +platform" column is blank — the number existed, but not
anywhere the agent or the UI could reach at response time.

That gateway change puts the same figures in the tool response itself, under
`result.structuredContent.token_usage`. This module accumulates them across every
MCP call in a turn so the agent can publish an agent+platform total beside its own.

Two properties of the upstream contract are deliberately preserved here:

*   **Absence is meaningful.** A turn served from the platform's response or plan
    cache ran no LLM call of its own and reports NO `token_usage`, rather than a
    zero it did not measure. `get_platform_usage()` therefore returns None for a
    turn in which nothing was reported, and the UI renders "—" rather than "$0.0000".
*   **The token counts are exact; the money is an ESTIMATE.** The platform prices
    each phase at the model's published list rate, which carries no negotiated
    discount and goes stale when a provider moves its prices. We pass its own
    `*_cost_usd` figures through untouched rather than re-deriving them, so there is
    one number, owned by the side that knows which models actually ran.
"""

from __future__ import annotations

from contextvars import ContextVar

# Same ContextVar-holding-a-mutable-dict shape as app.llm._turn_usage, and for the
# same reason: an asyncio task copies the context at creation, so a task spawned
# mid-turn sees this dict and its in-place mutations, whereas a .set() from inside
# that task would be invisible to the streaming generator that reads the totals.
_turn_platform_usage: ContextVar[dict | None] = ContextVar(
    "_turn_platform_usage", default=None
)

# `calls` counts MCP calls that REPORTED usage, not MCP calls made — a cache-served
# call contributes nothing and must not read as a zero-cost model call.
_ZERO = {
    "prompt_tokens": 0,
    "cached_input_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "input_cost_usd": 0.0,
    "cached_input_cost_usd": 0.0,
    "output_cost_usd": 0.0,
    "total_cost_usd": 0.0,
    "calls": 0,
}

_INT_FIELDS = ("prompt_tokens", "cached_input_tokens", "completion_tokens", "total_tokens")
_COST_FIELDS = ("input_cost_usd", "cached_input_cost_usd", "output_cost_usd", "total_cost_usd")


def reset_platform_usage() -> None:
    """Begin a new turn. Call once per user message, before the graph runs."""
    _turn_platform_usage.set(dict(_ZERO))


def get_platform_usage() -> dict | None:
    """Platform totals for this turn, or None when the platform reported none.

    None and a zeroed dict mean different things: None is "the platform ran no LLM
    call it charged us for" (cache hit, or a gateway too old to report), which the UI
    shows as "—". A dict with zeros would claim we measured a free call.
    """
    acc = _turn_platform_usage.get()
    if acc is None or acc["calls"] == 0:
        return None
    out = dict(acc)
    # Summing raw IEEE doubles gives a sum with no exact binary form: two calls at
    # 0.0003 and 0.0001 serialise as 0.00039999999999999996 for a field we present as
    # money. Rounded at 10dp, the same place and for the same reason as the gateway's
    # own `usd()` helper — far below the smallest unit any rate card can produce, so
    # this drops the artefact without dropping spend.
    for field in _COST_FIELDS:
        out[field] = round(out[field], 10)
    return out


def record_platform_usage(token_usage: dict | None) -> None:
    """Fold one MCP call's `token_usage` section into this turn's totals.

    A no-op when the section is absent (cache hit, pre-#1164 gateway) or when called
    outside a turn, so neither an old platform nor library use of the client fails here.

    :param token_usage: `structuredContent.token_usage` from one MCP tool response.
    """
    if not token_usage:
        return
    acc = _turn_platform_usage.get()
    if acc is None:
        return

    # Defensive coercion: these cross a process boundary as JSON, and a field the
    # gateway omits (no cached-input tier on the model that ran) arrives as absent,
    # not 0. A malformed value must not take down a data call that already succeeded.
    for field in _INT_FIELDS:
        try:
            acc[field] += int(token_usage.get(field) or 0)
        except (TypeError, ValueError):
            pass
    for field in _COST_FIELDS:
        try:
            acc[field] += float(token_usage.get(field) or 0.0)
        except (TypeError, ValueError):
            pass
    acc["calls"] += 1
