# Every LLM call in Marvi, and what it carries

The companion to `PROVIDER-PIPELINE.md`. That document compared chat and voice;
this one is the full census, because the question "who owns an LLM call" has
more than two answers and the others are where the surprises are.

Traced from the code, not from memory.

## The census

| Consumer | How it reaches a provider | Through `ProviderClient`? | What identity it sends |
|---|---|---|---|
| **Chat** (`chat.py`) | `ProviderClient.call_with_fallback()` | **Yes** | `identity.compose()` — SOUL.md, USER.md, the chat brief, curiosity guidance, plugin context lines |
| **Cortex mind** (`mind.py` → `deliberate.py`) | shared `CognitionHarness` → `ProviderClient.call_with_fallback(job="aux")`, Auxiliary `mind` role | **Yes** | SOUL.md, USER.md, current date/time, bounded decision task, event envelope; bounded read-only tools |
| **Presence judgement** (`presence.py`) | `ProviderClient.call_with_fallback(job="aux")`, Auxiliary `mind` role | **Yes** | a presence-specific bounded prompt |
| **Cortex reflection** (`memory.py` → `distil.py`) | shared `CognitionHarness` → `ProviderClient.call_with_fallback(job="aux")`, Auxiliary `memory` role | **Yes** | SOUL.md, USER.md, current date/time, repeated subjects/counts; bounded memory/web/workspace reads |
| **Distillation** (`distil.py`) | `ProviderClient.call_with_fallback(job="aux")`, named Auxiliary role | **Yes** | task-specific title/web prompts |
| **Voice** (`marvi_agent/runtime.py`) | `livekit.plugins.openai.LLM`, direct to the provider | **No** | a hardcoded `instructions=` string in `session.py` |
| **Vision** (`describe.py`) | raw `httpx.post(f"{base_url}/chat/completions")` | **No** | its own `PROMPT` constant |

Two more that look like LLM users and are not:

- **Smart room** does not call a model. It is a *tool provider*: the room's
  tools are registered into the router and a model calls them during someone
  else's turn. There is no room turn.
- **Memory recall, ingest, graph projection, and consolidation** are
  deterministic and do not call a model. Reflection first asks the Auxiliary
  `memory` role to summarise repeated subjects; an absent/failed/empty model
  result continues through deterministic promotion.
- **Curiosity** has no client. It picks *which* question is due by rule, and
  appends the wording to the chat prompt for the model already running.

## Two things this shows

### 1. There is no single source of truth for the call

`ProviderClient` is the *intended* one. It owns fallback across providers,
cooldown after a rejected credential or a 429, token and billable accounting,
cache policy, structured route/latency diagnostics and limit policy. Chat, Cortex,
presence, and distillation go through it. **Voice and Vision do not.**

Vision is the further gone of the two: it has its own credentials entirely —
`MARVI_VLM_BASE_URL` and `MARVI_VLM_API_KEY` — so it is not merely bypassing
the client, it is bypassing the *registry*. A provider connected in the control
centre is invisible to vision, and the vision endpoint is invisible to the
Providers page.

So the answer to "which is the source of truth" is: `ProviderClient` should be,
and is for half the callers.

### 2. There is no single source of truth for the harness

`identity.compose()` now feeds both Chat and the shared Cortex cognition harness.
Mind and memory reflection therefore receive the same durable identity prefix,
while retaining small task-specific instructions and Auxiliary routing. Voice
and Vision still have separate latency/media-specific call paths.

The remaining identity gap is Voice and Vision, not Mind or memory reflection.

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
3. Providers-as-documents, model choice, effort, and auxiliary slots now exist;
   keep every new background caller on the shared `job="aux"` role boundary.
4. Then the surfaces.

Doing 3 before 1 and 2 means implementing model choice and reasoning effort
four times.
