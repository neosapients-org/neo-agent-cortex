# agent-cortex

One of two agents built to compare **where data comes from**, holding everything else equal.
This one asks the Cortex platform in plain English and gets rows back. The other (agent-claude) does the opposite.

Both run Claude Sonnet 5 through the same pipeline; the only intended difference is the
data-fetch step, so any cost or quality gap is attributable to that.

## Run it

```bash
cd apps/agent && .venv/bin/python -m uvicorn app.main:app --port 8000
```

Chat UI is served by the agent itself at <http://localhost:8000>. Allow ~40s to become
healthy — it front-loads context at boot, so an earlier health check is a false alarm.

See [RUNBOOK.md](RUNBOOK.md) first: it lists four things that silently disable observability
with no error message.

## Layout

| Path | |
|---|---|
| `apps/agent/app/` | the whole agent — FastAPI, LangGraph pipeline, chat UI |
| `apps/agent/app/mcp/client.py` | the data-path seam; the single `if` that separates the two variants |
| `apps/agent/app/static/index.html` | the chat page served at `/` |
| `packages/ns_probe/` | observability SDK, installed editable — **must** be installed or traces vanish silently |

## Reading order

1. [DECISIONS.md](DECISIONS.md) — why it is built this way
2. [FLOW.md](FLOW.md) — one question, start to finish
3. [RUNBOOK.md](RUNBOOK.md) — running it, and the traps
