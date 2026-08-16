# Phase 9 — Providers, Auxiliary Models, and Identity

**Status:** planned
**Depends on:** Phase 6 (the deliberation seam), Phase 5 (memory)

Marvi currently speaks to exactly one model through one hardcoded HTTP call, and
has no written idea of who it is or who it is talking to. This phase fixes both.

> **Correction — and why LiteLLM is out of scope.** An earlier draft proposed
> LiteLLM as a routing layer. That was wrong twice over.
>
> LiteLLM is a **proxy**, not a provider. It is its own product, with its own
> CLI and its own web UI, and the user configures their providers *inside it*.
> Adopting it would mean Marvi talks to LiteLLM, which talks to the provider —
> an extra hop, an extra service to supervise, and a second place where provider
> configuration lives. Marvi should talk to providers directly. If someone
> already runs LiteLLM, it is simply an OpenAI-compatible endpoint like any
> other and needs no special support.
>
> The second error was framing this as per-token API keys. Marvi must support
> **both access paths to the same vendor**: the metered API *and* the
> subscription plan. OpenAI sells an API and a Codex plan. Anthropic sells an
> API and Claude Code. Those are different endpoints, different auth, and
> different billing — so they are different profiles, not one provider with a
> flag.

## The shape: a provider profile registry

The predecessor assistant solves this with a registry of provider *profiles*,
one plugin per provider, and it is the right model to adapt. Its profile carries
everything that differs between vendors:

```
name, aliases                     identity and the names users actually type
display_name, description         for a picker
signup_url                        where to go to get access
auth_type                         api_key | oauth_device_code | oauth_external
                                  | subscription | cloud_sdk
env_vars, base_url, models_url    where the endpoint lives
api_mode                          chat_completions | responses
supports_vision                   capability flags that change behaviour
supports_prompt_cache_key
supports_health_check
default_aux_model                 the cheap model this provider offers
default_vision_model
fallback_models
default_headers, fixed_temperature, default_max_tokens
prepare_messages()                per-vendor request shaping
build_extra_body()
fetch_models()
```

Two things in that list matter more than the rest, and both were missing from
the earlier draft:

- **`auth_type` is a first-class field.** A provider is not "a base URL plus a
  key". Codex authenticates against a ChatGPT account, Copilot against a GitHub
  subscription, Qwen through an external OAuth flow. Each needs a different
  acquisition path and a different refresh story, and the profile is where that
  belongs.
- **`default_aux_model` lives on the provider.** Auxiliary models are not a
  separate routing system; each provider already knows which of its own models
  is the cheap one. That is a much smaller idea than a learned router, and it
  composes: pick a provider, and the auxiliary model comes with it.

Marvi will write its own registry rather than copy the implementation — the
predecessor's is coupled to its plugin loader and CLI — but the profile shape
and `auth_type` vocabulary are worth adopting directly.

## Three access paths, not three vendors

The registry is organised by **how you reach a model**, not by who makes it. A
vendor with two access paths gets two profiles, because everything that differs
between them lives in the profile.

**1. Metered APIs** — a key, a meter, pay per token.

| Provider | Auth | Notes |
|---|---|---|
| OpenRouter | `api_key` | many models behind one key |
| DeepInfra | `api_key` | OpenAI-compatible |
| DeepSeek | `api_key` | |
| OpenAI | `api_key` | the API, distinct from the Codex plan below |
| Anthropic | `api_key` | the API, distinct from Claude Code below |
| OpenCode Go | `api_key` | what Marvi uses today |

**2. Subscriptions and coding plans** — reached through an account the user
already pays for, over OAuth. Same vendors as above in several cases, different
endpoint and different auth.

| Provider | Auth | Uses |
|---|---|---|
| Codex | `oauth_external` | a ChatGPT subscription |
| Claude Code | `oauth_external` | an Anthropic plan |
| GitHub Copilot | token exchange | a Copilot seat |
| Qwen | `oauth_external` | a Qwen portal account |
| Alibaba, Kimi coding plans | mixed | monthly vendor plans |

**3. Local** — the user's own hardware, no account and no meter. These matter
disproportionately for a local-first product: they are the only providers that
keep working with the network down, and the only ones with no privacy question
at all.

| Provider | Auth | Endpoint |
|---|---|---|
| Ollama | none | `http://localhost:11434/v1` |
| LM Studio | none | `http://localhost:1234/v1` |
| llama.cpp / vLLM | none | user-configured |

All three local options serve an OpenAI-compatible API, so one `local` profile
with a configurable `base_url` covers them, with named presets for the common
ports rather than a separate plugin each. A running LiteLLM proxy, if the user
has one, is just another entry here.

Consequences worth stating up front:

- **A vendor is not a provider.** `openai` and `codex` are two profiles, as are
  `anthropic` and `claude-code`. Selecting a model means selecting an access
  path. Aliases keep this friendly — typing `claude` should resolve to whichever
  Anthropic path is actually configured.
- **Marvi never sees a password.** OAuth happens in the provider's own surface,
  the same rule Composio already follows (ADR-016). Marvi receives a token.
- **Tokens expire; API keys mostly do not.** Refresh, and a clear "reconnect
  this provider" state, are core to the phase rather than polish. The
  revoked-OAuth handling built for Composio in Phase 5 is the precedent.
- **Three billing models, one budget guard.** Metered APIs cost money per
  token, subscriptions meter requests per window, and local models cost
  nothing. The `daily_budget` in `REAL-AGENCY.md` only understands money, so it
  silently stops binding on a plan and pointlessly throttles a local model.
  It needs a unit per access path.
- **Token storage is a real decision.** Refresh tokens are credentials at rest.
  Windows DPAPI is the local option; the alternative is deferring storage to the
  provider's own CLI where one exists.

## What this unblocks

- **Phase 8's missing VLM.** `supports_vision` and `default_vision_model` turn
  "OpenCode Go has no vision model" from a dead end into provider selection.
  `describe.py` already speaks the right shape and is waiting.
- **Failover that means something.** `fallback_models` plus a health probe
  covers the case that actually happens: one subscription is rate-limited or
  expired, and the work should continue somewhere else.
- **One boundary for two callers.** `session.py` and `deliberate.py` currently
  each carry their own provider knowledge. Until they share a registry, adding a
  second provider only works in half the app.

## Identity — `SOUL.md` and `USER.md`

An established convention, and the useful lesson from every implementation of it
is that these files are **short**. The predecessor's are roughly 0.5 KB and
1.3 KB against a 4 KB memory file; `AGENTS.md` already requires the voice prompt
to stay small, and every token here is paid on every turn.

- **`SOUL.md`** — who Marvi is: voice, temperament, what it refuses. Changes
  rarely. Authored by the user; never written by Marvi.
- **`USER.md`** — who the user is: name, pronouns, hours, standing preferences.
  Marvi may *propose* additions through the existing confirmation flow, never
  edit silently, or the persona becomes self-modifying and unauditable.
- **Memory stays separate.** The line that stops this rotting: `USER.md` is what
  is true on every turn; memory is what happened. Relevant only sometimes means
  memory.

The prompt composer is a tested function with a token budget and a defined
truncation order — `SOUL.md` + `USER.md` + task instruction — because a prompt
that silently outgrows the context window is the failure mode here.

**The trust boundary must not blur.** Identity files are user-authored and may
shape behaviour. Anything recalled from memory, an account, or the web keeps its
envelope (ADR-015). Both end up near the prompt; only one of them is trusted.

## Work breakdown

1. **Provider profile registry** — the dataclass, `register_provider`, lookup by
   name and alias, and capability flags. No new dependency; this is our own
   small module.
2. **Auth strategies** — `api_key` first, then `oauth_external` and device code.
   Token storage, refresh, and an explicit expired state per provider.
3. **Move both callers onto it** — the voice session and the mind resolve models
   through the registry, so a second provider works everywhere at once.
4. **Subscription accounting** — extend the budget to requests-per-window
   alongside money, so the `REAL-AGENCY.md` guard still binds on a plan.
5. **Auxiliary models via `default_aux_model`** — classification, extraction and
   deliberation move to the provider's cheap model. A local provider is the
   natural home for auxiliary work: free, private, and always available. If a
   local model runs on this machine it is CPU-first, because Phase 8 put vision
   on the CPU and PocketTTS is there too, and the GPU budget is already spent.
6. **Identity files and composer** — schema, budget, editor surface.
7. **Providers page** — which providers are connected, which need reconnecting,
   which model serves each job, and what has been spent or consumed today.

## Acceptance evidence required

- One provider from each access path working: a metered API, a subscription
  reached by OAuth without Marvi handling a password, and a local endpoint.
- The same vendor configured on both paths at once — for instance the OpenAI
  API and Codex — selectable independently and billed independently.
- A local provider still answering with the network unavailable.
- An expired token surfaces as "reconnect this provider" rather than a failure,
  and reconnecting restores service without a restart.
- Killing the primary provider degrades to a fallback with no user-visible
  error, and the audit records which provider served each call.
- A vision-capable provider makes `vision_describe` work with no change to
  `describe.py`.
- Subscription quota is tracked and stops background thinking when exhausted,
  the same way the money budget does.
- `SOUL.md` and `USER.md` measurably change behaviour while the composed prompt
  stays inside its stated budget, and the Phase 5 injection tests still pass
  with identity loaded.

## Risks

- **OAuth flows are per-vendor and change.** Each is bespoke and can break
  without notice. Start with one, prove refresh and revocation, then add more.
- **Refresh tokens at rest are credentials.** Storage needs deciding
  deliberately, not defaulted into a JSON file.
- **Subscription terms.** Driving a coding-plan subscription from an ambient
  assistant may sit outside what that plan permits. Worth checking per provider
  before shipping, not after.
- **Prompt bloat** on the latency-critical voice path Phase 3 tuned hard. The
  budget is enforced in code, not by intention.
