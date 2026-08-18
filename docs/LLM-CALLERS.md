# Every LLM call in Marvi, and what it carries

The companion to `PROVIDER-PIPELINE.md`. That document compared chat and voice;
this one is the full census, because the question "who owns an LLM call" has
more than two answers and the others are where the surprises are.

Traced from the code, not from memory.

## The census

| Consumer | How it reaches a provider | Through `ProviderClient`? | What identity it sends |
|---|---|---|---|
| **Chat** (`chat.py`) | `ProviderClient.call_with_fallback()` | **Yes** | `identity.compose()` — SOUL.md, USER.md, the chat brief, curiosity guidance, plugin context lines |
| **Mind** (`mind.py` → `deliberate.py`) | `ProviderClient` | **Yes** | its own `SYSTEM_PROMPT` constant |
| **Voice** (`marvi_agent/runtime.py`) | `livekit.plugins.openai.LLM`, direct to the provider | **No** | a hardcoded `instructions=` string in `session.py` |
| **Vision** (`describe.py`) | raw `httpx.post(f"{base_url}/chat/completions")` | **No** | its own `PROMPT` constant |

Two more that look like LLM users and are not:

- **Smart room** does not call a model. It is a *tool provider*: the room's
  tools are registered into the router and a model calls them during someone
  else's turn. There is no room turn.
- **Memory** — `memory.reflect()` takes an optional `summarise` callable and
  every caller (`initiative.run_reflect`, the `/memory/reflect` endpoint)
  passes nothing. So reflection is deterministic today, not a model call.
  Consolidation likewise. Worth knowing before anyone points a model at it.
- **Curiosity** has no client. It picks *which* question is due by rule, and
  appends the wording to the chat prompt for the model already running.

## Two things this shows

### 1. There is no single source of truth for the call

`ProviderClient` is the *intended* one. It owns fallback across providers,
cooldown after a rejected credential or a 429, token and billable accounting,
cache policy and limit policy. Chat and Mind go through it. **Voice and Vision
do not.**

Vision is the further gone of the two: it has its own credentials entirely —
`MARVI_VLM_BASE_URL` and `MARVI_VLM_API_KEY` — so it is not merely bypassing
the client, it is bypassing the *registry*. A provider connected in the control
centre is invisible to vision, and the vision endpoint is invisible to the
Providers page.

So the answer to "which is the source of truth" is: `ProviderClient` should be,
and is for half the callers.

### 2. There is no single source of truth for the harness

`identity.compose()` — the function that assembles SOUL.md and USER.md into a
prompt — has **exactly one caller**: `chat.py:174`.

That means the identity files, the ones Marvi is supposed to keep filling in by
asking the user questions, reach the typed surface and nowhere else. Voice, the
primary interface, has a different personality written as a Python string
literal. Mind has a third. Vision has a fourth.

Four Marvis, and only one of them knows the user's name.

**Is the harness sent on every turn?** For chat, yes: `_system()` runs per turn
and `identity.compose()` is called each time, with the identity block first
precisely so the prefix stays byte-identical and cacheable, and the volatile
parts — curiosity, plugin context — appended after it. For voice, LiveKit sends
`instructions` once when the `Agent` is constructed and reuses it for the
session. For mind and vision, a constant goes out with each request.

## What a single pipeline has to unify

Not just the transport. Three things travel together and all three are
currently per-caller:

1. **Who to call** — provider, model, credentials. Registry today for chat,
   mind and voice; separate env vars for vision.
2. **How to call** — fallback, cooldown, accounting, reasoning effort.
   `ProviderClient` for chat and mind; nothing for voice and vision.
3. **What to say first** — the identity and the task brief. One composer for
   chat; three hardcoded strings elsewhere.

A pipeline that unifies only the first two still leaves four different Marvis.
The harness belongs in the same seam:

    caller (chat | voice | mind | vision | a future one)
      → declares its task and its surface
      → Gateway composes: identity + task brief + volatile context
      → ProviderClient: chooses, calls, retries, records
      → provider

with the task deciding what varies — voice gets "short sentences, no Markdown",
vision gets "describe this frame" — and identity being the part that never
does.

That also gives auxiliary task slots somewhere to live: a slot is a *task*
name, and the task is already the thing being declared at the top of this
pipeline.

## Order

This changes the plan in `PHASE-12-PROVIDERS.md` again, and for the better:

1. **One call seam.** Every caller goes through `ProviderClient`, including
   voice via a `GatewayLLM` adapter and vision via the registry instead of its
   own env vars. Measure voice first-token latency before and after.
2. **One harness seam.** `identity.compose()` gains a task parameter and every
   caller uses it. Three string literals are deleted.
3. Then providers-as-documents, `models.py`, `effort.py`, `ModelChoice`,
   auxiliary slots — each of which now has exactly one place to be implemented.
4. Then the surfaces.

Doing 3 before 1 and 2 means implementing model choice and reasoning effort
four times.
