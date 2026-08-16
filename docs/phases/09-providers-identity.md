# Phase 9 — Providers, Auxiliary Models, and Identity

**Status:** planned
**Depends on:** Phase 6 (the deliberation seam), Phase 5 (memory)

Marvi currently speaks to exactly one model through one hand-rolled HTTP call,
and has no written idea of who it is or who it is talking to. This phase fixes
both, and they belong together: a persona is only meaningful if it survives
being routed to a different model.

## Scope

1. A provider layer: several LLM providers behind one boundary, with failover.
2. Auxiliary models: small, cheap models doing the work that does not need a
   frontier model.
3. Identity: `SOUL.md`, `USER.md`, and a composed system prompt with a budget.
4. Provider credentials, including OAuth, without Marvi ever holding a password.

## Where things stand today

Worth being precise, because it shapes the work:

- `deliberate.py` posts to one hardcoded OpenAI-compatible endpoint. There is no
  retry, no fallback, no cost accounting beyond a flat per-call estimate, and no
  model selection.
- `session.py` builds the voice LLM through `openai.LLM(...)` with a single
  base URL. Two separate code paths already talk to the same provider.
- `describe.py` waits for a vision provider that OpenCode Go does not offer —
  verified against 26 models, none of which accept image content.
- `announce.py` and the voice stack already prove the "two engines for two jobs"
  pattern: PocketTTS on CPU for one-shot speech, VibeVoice on GPU for streaming.
  Auxiliary models are the same idea applied to language.
- There is no `SOUL.md` or `USER.md` in this repo. The predecessor assistant
  keeps small ones (roughly 0.5 KB and 1.3 KB) alongside a larger `MEMORY.md`,
  which is a useful sanity check on size: identity is short, memory is long.

## Research

### Provider abstraction — LiteLLM

[LiteLLM](https://docs.litellm.ai/) is the strongest candidate and, importantly,
works as a **Python library** rather than only a proxy server, so it does not
add a service to supervise. `litellm.Router` provides, verified from the
[reliability docs](https://docs.litellm.ai/docs/proxy/reliability):

- ordered fallbacks between models and providers;
- **context-window fallbacks** — automatically move to a larger model when the
  input will not fit, which is exactly the failure the mind will hit as memory
  grows;
- content-policy fallbacks, for a refusal from one provider;
- `num_retries`, `request_timeout`, `allowed_fails` and `cooldown_time`, so a
  provider having a bad hour is routed around rather than retried into.

The cooldown behaviour matters more than the fallback list. Marvi's background
mind runs unattended, and a provider that is failing slowly is worse than one
that is failing fast.

**Open question to settle by measurement:** LiteLLM is a large dependency, and
ADR-014 rejected mem0 partly on dependency weight and bundled telemetry. LiteLLM
must be checked for the same things before adoption — dependency count, whether
it phones home by default, and whether it can be pinned without pulling a
provider SDK for every vendor.

**Fallback if it fails those gates:** the provider boundary is small enough to
own. `deliberate.py` already speaks the OpenAI-compatible shape in about 40
lines, and every provider in scope (OpenCode Go, OpenRouter, local llama.cpp,
vLLM) exposes that shape. A hand-rolled router with ordered fallback, cooldown,
and a cost table is perhaps 150 lines and zero new dependencies.

### Model routing — do not over-build it

The 2026 routing literature is mostly about serving cost at scale: classify each
request and dispatch to the cheapest adequate model. That is a real technique,
but Marvi's traffic is tiny and its jobs are already known and separable. Routing
by **job**, not by learned classification, gets nearly all the benefit for none
of the machinery:

| Job | Wants | Candidate |
|---|---|---|
| Foreground voice turn | lowest first-token latency | fast hosted model |
| Background deliberation | cheap, structured, tolerant of latency | small model |
| Reflection and summarisation | quality over speed, runs rarely | stronger model |
| Scene description | vision | whatever provider has one |
| Classification and extraction | near-free, no network ideally | local auxiliary |

A learned router is deferred until there is a measured case where job-based
routing picks wrong.

### Auxiliary models

The point is not capability, it is **not paying a frontier model to do
arithmetic**. Candidates, all small enough to sit beside the voice stack:

- **Local embeddings.** ADR-014 shipped SQLite FTS5 with the note "revisit when
  retrieval quality measurably fails". A small CPU embedding model is the
  natural upgrade path when it does — and it is the one auxiliary model with a
  clear trigger already written down.
- **A local instruct model** (Qwen/Phi class, quantised, CPU or a slice of GPU)
  for: is this event worth surfacing, extract entities from this text, is this
  spam. All of these currently either do not happen or cost a network round
  trip through `deliberate.py`.
- **Reranking**, only if retrieval quality proves to be the bottleneck.

**Hard constraint:** the RTX 3060 budget is spoken for. Phase 3 measured
4.245 GiB with 2 GB of required headroom, and Phase 8 put vision on the CPU for
exactly this reason. Any auxiliary model is CPU-first, and must be shown not to
disturb voice latency before it becomes a default.

### Identity — `SOUL.md` and `USER.md`

`SOUL.md` is an established convention rather than an invention: the predecessor
assistant, [OpenClaw](https://www.stanza.dev/concepts/openclaw-soul-persona), and
[aeonfun/soul.md](https://github.com/aeonfun/soul.md) all use a short persona
file loaded into the system prompt. The consistent lesson across them is that
these files are **short**. The predecessor's are half a kilobyte and a kilobyte;
`AGENTS.md` already requires the voice prompt to stay small, and every token
here is paid on every turn.

Proposed split, chosen so each file has one owner and one lifetime:

- **`SOUL.md`** — who Marvi is. Voice, temperament, what it refuses. Changes
  rarely, authored by the user, never written by Marvi.
- **`USER.md`** — who the user is. Name, pronouns, working hours, preferences,
  the things worth knowing on every single turn. Authored by the user; Marvi may
  *propose* additions through the existing confirmation flow but never edits it
  silently.
- **Memory** stays where it is. The distinction that keeps this from rotting:
  `USER.md` is what is true on every turn, memory is what happened. If something
  is only relevant sometimes, it is memory, not identity.

## Design decisions to make in this phase

1. **One provider boundary, two callers.** `session.py` and `deliberate.py`
   currently duplicate provider knowledge. Both should resolve a model through
   one registry, or the second provider added will only work in half the app.
2. **Prompt composition is a function, and it is tested.** `SOUL.md` +
   `USER.md` + tool context + task instruction, assembled in one place with a
   token budget and a defined truncation order. A prompt that silently grows
   past the context window is the failure mode here, and the one LiteLLM's
   context-window fallback would otherwise mask.
3. **Identity files are trusted input; memory is not.** `SOUL.md` and `USER.md`
   are authored by the user, so they may shape behaviour. Anything recalled from
   memory or an account keeps its envelope (ADR-015). This boundary must not
   blur just because both end up near the prompt.
4. **Credentials never touch Marvi.** OAuth flows belong in the provider's own
   surface, exactly as Composio already works. Marvi reads keys from the
   environment and stores none.

## Work breakdown

1. **Provider registry** — evaluate LiteLLM against the ADR-014 gates
   (dependency weight, telemetry, pinning). Adopt it or write the small router.
   One boundary; both callers move onto it.
2. **Model policy** — job-based selection with per-job overrides in config, and
   a real cost table replacing `ESTIMATED_COST_PER_CALL`, so the daily budget in
   `REAL-AGENCY.md` binds against actual spend.
3. **Failover evidence** — a provider that 500s, a provider that times out, one
   that refuses on content policy, and an input too large for the primary. Each
   must degrade rather than surface an error to the user.
4. **Auxiliary model spike** — one CPU instruct model behind the deliberation
   seam. Measure decision quality against the deterministic baseline and against
   the hosted model, plus its effect on voice latency while resident.
5. **Identity files** — `SOUL.md` and `USER.md` with a documented schema, a
   composer with a token budget, and an editor surface in the control center.
6. **Provider settings UI** — which providers are configured, which model each
   job uses, what today's spend is.

## Acceptance evidence required

- Two providers configured; killing the primary degrades to the secondary with
  no user-visible error, and the audit records which provider served each call.
- A prompt exceeding the primary's context window is handled deliberately —
  either by fallback or by documented truncation — never by a silent failure.
- Cost accounting reflects real token usage, and the daily budget stops
  background thinking when it is exhausted.
- An auxiliary model runs a full day of deliberation with voice first-token
  latency unchanged within measurement error.
- `SOUL.md` and `USER.md` measurably change behaviour, and the composed prompt
  stays inside a stated token budget with both present.
- Identity files shape behaviour while recalled memory still cannot — the
  Phase 5 injection tests must still pass with identity loaded.

## Risks

- **Prompt bloat is the likeliest regression.** Every token in `SOUL.md` and
  `USER.md` is paid on every turn, including the latency-critical voice path
  Phase 3 worked hard on. The budget needs to be enforced in code, not by
  intention.
- **LiteLLM may fail the dependency gates.** Deciding that early avoids building
  the phase around something that then has to be removed.
- **A local auxiliary model competing for CPU** with PocketTTS announcements and
  CPU face recognition is a real contention risk, not a theoretical one. Both of
  those were put on the CPU deliberately.
- **Identity drift.** If Marvi can edit `USER.md` unsupervised, the persona
  becomes self-modifying and unauditable. Proposals go through confirmation, the
  same as any other write.
