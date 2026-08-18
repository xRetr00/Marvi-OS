# The provider pipeline: who owns an LLM call

Written to answer a direct question — *from chat or voice, all the way to the
provider, is there one pipeline?* The honest answer today is **no**, there are
two, and only one of them has the safety machinery. This document says exactly
where they diverge, what the divergence costs, and what the single pipeline
should look like.

## Today: two paths

### Chat

    renderer → IPC → Gateway POST /chat → Chat.send()
      → ProviderClient.call_with_fallback()
        → provider HTTP

### Voice

    LiveKit AgentSession (owns the turn)
      → marvi_agent.runtime.build_llm()
        → livekit.plugins.openai.LLM
          → provider HTTP

The agent asks the Gateway `GET /providers/voice` for *which* provider, model,
base URL and key to use — so the registry really is the single source of truth
for **selection**. `runtime.py`'s docstring says so, and it is right about that.

But selection is where the Gateway's involvement ends. `build_llm` hands those
four values to LiveKit's OpenAI plugin, and every token after that flows
between the plugin and the provider. The Gateway never sees the call.

## What the voice path does not get

`ProviderClient` is where the operational behaviour lives. Voice bypasses all
of it:

| `ProviderClient` gives | Voice gets |
|---|---|
| `call_with_fallback` — try the next provider when one fails | nothing; one provider, one chance |
| `stand_down` / `resting` — cooldowns after auth failure or 429 | nothing; a provider "cooling down 21600s" is still called |
| `record` / `usage_by_provider` — token and billable accounting | nothing; voice tokens are invisible |
| `CachePolicy`, `LimitPolicy` per provider | nothing |
| `reachable` probing | only once, at resolve time |

Concrete consequences, all present in the current build:

- The Providers page usage figures are **chat-only**. A day of voice costs
  nothing on that screen.
- The cooldowns in `errors.log` (`provider openai cooling down 21600s:
  authentication rejected`) protect chat and not voice.
- A reasoning-effort setting added in Phase 12 would have to be implemented
  twice, in two languages of request-shaping, or it silently applies to chat
  only.

## The assumption that will break next

`build_llm` is commented:

> Every provider Marvi speaks to on the voice path is OpenAI-compatible.

`/providers/voice` enforces that by filtering to `api_mode == "chat_completions"`,
so today it is true by construction. But it is true because the endpoint
*excludes* everything else, not because everything else works. Connect
Anthropic and it is simply absent from voice, with no explanation on any
screen. The user picked a main model; voice quietly used a different provider.

That is the same class of bug as the room's invented event names and the
provider "connected" badge: a surface saying one thing while the system does
another.

## Who owns a turn

**Voice: LiveKit owns it.** `AgentSession` runs the loop — VAD, the local
turn detector (`inference.TurnDetector(version="v1-mini")`), STT, the LLM call,
TTS, and interruption. This is correct and should not change. LiveKit is very
good at the part that is hard: deciding when a human has stopped talking.

**Chat: the Gateway owns it.** `Chat.send()` composes the system prompt,
appends history, calls the provider, dispatches tools, and records the turn.

So the turn owners are different, and they *should* be — a voice turn has
barge-in and end-of-utterance detection that a typed turn does not. The mistake
is not that the turn owners differ. **The mistake is that the provider call
differs.**

## Is LiveKit the source of truth for LLM calls?

No, and it should not become one. LiveKit owns **media and turn-taking**. It
should not own credentials, provider failover, spend accounting or reasoning
configuration — it has no view of the other surface, and every policy put there
is a policy chat does not get.

## The single pipeline

One rule: **every LLM call in Marvi goes through `ProviderClient`, whoever
started the turn.**

    voice turn ─┐
                ├→ Gateway /llm ─→ ProviderClient ─→ provider
    chat turn ──┘                     (fallback, cooldown, usage,
                                       cache, limits, effort)

The agent stops constructing its own client. Instead it is given an LLM adapter
that speaks LiveKit's interface and forwards to the Gateway:

```python
class GatewayLLM(livekit.agents.llm.LLM):
    """LiveKit's LLM interface, answered by Marvi's Gateway.

    LiveKit still owns the turn. It just no longer owns the provider.
    """
```

This is the standard extension point — LiveKit's plugins are themselves
implementations of that interface, so replacing `openai.LLM` with our own is
using the framework as designed rather than working around it.

What it buys:

- One place that knows what a call cost, so usage covers both surfaces.
- One cooldown, so a rejected credential stops both.
- One fallback chain.
- Reasoning effort, model choice and auxiliary routing implemented **once**.
- Anthropic, or any non-`chat_completions` provider, works on voice for free,
  because `ProviderClient` already speaks `api_mode`.

What it costs, stated honestly:

- **An extra hop on the hot path.** Voice is latency-sensitive; a loopback HTTP
  round trip per turn is real. It must stream — the Gateway endpoint has to be
  SSE or chunked, forwarding tokens as they arrive, or first-token latency gets
  visibly worse. This is the main risk and the thing to measure before
  committing.
- The Gateway becomes a hard dependency of speech. It already is — it issues
  the LiveKit token and owns every tool — so this changes degree, not kind.

## Providers as documents

The registry is code today: one `ProviderProfile(...)` literal per provider,
spread across `openai.py`, `anthropic.py`, `local.py`, `metered.py`,
`opencode.py`. Adding a provider means editing Python, and the fields a
provider needs are learned by reading other entries.

Phase 12 should move each provider to its own document under
`config/providers/<slug>.json`, loaded by the registry the way
`components.json` and `plugin-sources.json` already are:

```json
{
  "slug": "anthropic",
  "display_name": "Anthropic",
  "api_mode": "anthropic",
  "auth": { "type": "api_key", "env": ["ANTHROPIC_API_KEY"] },
  "base_url": { "default": "https://api.anthropic.com", "env": "ANTHROPIC_BASE_URL" },
  "models": { "path": "/v1/models", "shape": "anthropic" },
  "reasoning": { "shape": "anthropic_adaptive", "levels": ["low","medium","high","max"] },
  "limits": { "style": "tokens", "readable": false },
  "docs": "https://platform.claude.com/docs/"
}
```

Then adding a provider is adding a file, and the fields are visible rather than
inferred. One loader, one schema, one test that every file parses — and, per
the lesson from hermes's `provider_catalog.py`, **one catalog behind every
surface** with a parity test so a provider cannot exist for the CLI and not the
GUI.

## Auxiliary, corrected

My earlier summary was too coarse. Hermes does not have "an auxiliary model".
It has **eleven independent task slots** — title generation, vision,
compression, approval scoring, web extraction, skills search, MCP routing,
triage, decomposition, profile description, curation — each with its own block:

```yaml
auxiliary:
  compression:
    provider: auto        # the default
    model: ''
  vision:
    provider: openrouter  # an override
    model: google/gemini-2.5-flash
    base_url: ''
    api_key: ''
    timeout: 120
```

`provider: auto` with an empty model means *use the main model for this job
too*. When a task is on `auto`, resolution is:

1. the main model,
2. the task's own `fallback_chain`, if it has one,
3. the top-level `fallback_providers`,
4. the built-in discovery chain.

Two things matter for Marvi. First, auxiliary is **per task**, not one setting —
the user should be able to send vision somewhere cheap without moving
compression. Second, `auto` is a *mode*, not a copied value, so changing the
main model moves every task still on `auto`.

Marvi's tasks are its own, not hermes's. The honest starting set, from what the
code actually does today: vision description (`describe.py`), memory reflection
and consolidation (`memory.py`), chat title generation, and the curiosity
question picker (`curiosity.py`). Each gets a slot; each defaults to `auto`.

## Order

The pipeline unification comes **before** the Models page, not after. Building
model selection and reasoning effort on top of two call paths means building
them twice, and the second one will be the one that rots.

1. `GatewayLLM` and a streaming `/llm` endpoint; measure first-token latency
   against the current direct path and stop if it regresses badly.
2. Providers as documents, one loader, parity test.
3. `models.py`, `effort.py`, `ModelChoice` — Phase 12 as planned, now with one
   place to put them.
4. Auxiliary task slots.
5. The surfaces: Providers page, Models page, composer override.
