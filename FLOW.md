# How agent-cortex works

A walkthrough of one question, from typing it to reading the answer.

**In one line:** the agent asks the data platform a question in plain English, gets rows
back, and turns them into a readable answer.

---

## The pieces

| | |
|---|---|
| **Chat page** | served by the agent itself, at `http://localhost:8000` |
| **The agent** | decides what to do, talks to the platform, writes the answer |
| **Cortex platform** | holds the data, works out the query, returns rows |
| **Memory** | remembers facts about the user across conversations |
| **Recorder** | writes down every step and every model call, for the dashboard |

---

## One question, start to finish

```
You type a question
        │
        ▼
   ┌─────────────────────── the agent ────────────────────────┐
   │                                                          │
   │   These two run AT THE SAME TIME:                        │
   │                                                          │
   │   ┌── safety + memory ──┐   ┌── understand + fetch ───┐  │
   │   │ • is this question  │   │ • what are they asking? │  │
   │   │   allowed?          │   │ • which client? which   │  │
   │   │ • what do we know   │   │   metric? which period? │  │
   │   │   about this user?  │   │ • ask the platform ─────┼──┼──► Cortex
   │   └─────────────────────┘   └─────────────────────────┘  │      │
   │                                                          │   rows back
   │   Safety check failed? → refuse, throw the data away      │      │
   │   Passed? ─────────────────────────────────────────────► │ ◄────┘
   │                                                          │
   │   Write the answer, streaming it word by word            │
   │   Check the answer is safe to show                       │
   └──────────────────────────────────────────────────────────┘
        │
        ▼
You see the answer appear
```

### Why safety and data run together

The agent does not wait to be told the question is safe before it starts looking things up.
It starts both at once and throws the lookup away if the safety check fails.

That wastes a lookup on blocked questions and saves real time on the overwhelming majority
that are not blocked.

---

## What you actually see on screen

The chat page shows the agent's steps as they happen, not just the final answer:

```
parallel prep       Running input safety scan + loading memory
parallel prep       Safety check passed
intent enrichment   Intent classified as "fetch_data"
intent enrichment   Resolved data_type: aum · filters: ['client tier']
data fetch          Querying the Cortex platform for live data
data fetch          Sending to platform: "Show the AUM breakdown by client tier"
data fetch          1/1 platform query succeeded
generate response   Composing answer from 1 data source(s)

Here's the AUM breakdown by client tier:
| Client Tier | Total AUM | % of Total |
...
```

That trail is deliberate. It is what lets you see *what the agent did*, not just what it
said — and it is how the two agents are compared side by side.

---

## The data step, in a little more detail

This is the only part that differs from the other agent.

```
Agent  ──"Show the AUM breakdown by client tier"──►  Cortex platform
                                                          │
                                                    Cortex's own AI
                                                    turns that sentence
                                                    into a database query
                                                          │
                                                     runs it
                                                          │
Agent  ◄──────────── rows, as text ───────────────────────┘
```

The agent sends a sentence and gets data. It never writes a query, never sees a table name,
and never touches the database.

**Two consequences worth knowing:**

- **Cheap on our side.** Most of the thinking happens on the platform, so this agent
  typically makes only 2–3 model calls per question.
- **We cannot see the platform's working.** The query it built is never shown to us, so if
  an answer is wrong we can see *that* but not *why*.

---

## What gets recorded

Every turn produces:

- a record of the whole turn, with timing
- one record per model call, with tokens in and out
- a one-line summary row for the turn

All of it is tagged `agent-cortex`, which is how the dashboard tells the two agents apart.

**One honest gap:** the tokens the *platform* spends thinking are not in these records —
they are spent on its servers. So the cost shown here is the cost of our half only.
