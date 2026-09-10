# Decisions — agent-cortex

Why this agent is built the way it is. Plain English, one entry per decision that would
otherwise look arbitrary to someone reading the code.

This is one of two agents built to be compared. **The only intended difference between them
is where the data comes from.** This one asks the platform. The other queries the database
itself.

---

## 1. This agent does not write SQL

It sends the user's question to the platform in plain English and gets rows back. The
platform works out which tables to read and builds the query itself.

The agent never sees a table name.

## 2. It uses the same AI model as the other agent

Both agents run Claude Sonnet. That was a deliberate change: originally this one was going
to keep its old, much cheaper model.

**Why:** comparing a small cheap model against a large one would mostly measure "small model
is cheaper", which we already know. Same model on both sides means any cost difference comes
from the thing we actually want to study — how each one gets its data.

## 3. Everything except the data step is identical to the other agent

Same code, same steps, same prompts. The swap happens deep inside, at the single point where
data is fetched.

**Why:** if the two agents differed in several places, we could not say which difference
caused a cost or quality gap. One variable, or the comparison means nothing.

## 4. The platform's real address stays in the code

The repository carries no product name anywhere — with one exception: the address of the
data platform this agent talks to.

**Why:** it is a live address, not a label. Renaming it produced something that looked like a
valid address but did not exist, and the resulting failure looked like a network problem
rather than a rename. A settings file can override it; the code keeps a working default so
the agent still runs if that setting is missing.

## 5. Every platform call carries a tracing id

The platform runs **its own AI** to turn our question into a query. That work costs money,
but it happens on the platform's servers, so we never see it.

Without a shared id those costs land in a completely separate record and this agent looks
cheaper than it really is. Sending the id is an attempt to stitch the two halves together.

**Still unconfirmed:** whether the platform picks the id up. Until it does, treat this
agent's reported cost as a floor, not a measurement.

## 6. Recording is not optional

Every conversation turn is recorded — the steps taken, the model calls made, the tokens used.

**Why it needs saying:** the recording tool fails quietly. If it is not installed, or if the
settings are read too late, it simply records nothing — no error, no warning — and the
dashboard shows the agent as free rather than broken. This has happened twice. If the
numbers look absent, suspect the recorder before suspecting the agent.

## 7. Known limitation: we cannot check the platform's work

The platform generates its query on its own servers and does not show it to us. So when an
answer looks wrong, we can see *what* it returned but not *how* it got there.

This is worth knowing because it already mattered: on one comparison this agent reported a
total roughly six times too high, and we could only tell because the other agent — whose
query we *can* read — produced a different number we were able to verify.
