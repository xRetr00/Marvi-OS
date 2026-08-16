# Phase 9 — Providers, Auxiliary Models, and Identity

**Status:** in progress — foundation shipped
**Depends on:** Phase 6 (the deliberation seam), Phase 5 (memory)

Marvi currently speaks to one model through one hardcoded HTTP call, and has no
written idea of who it is or who it is talking to. This phase fixes both.

## Two rejected shapes, recorded so they are not revisited

**LiteLLM is out of scope.** It is a *proxy*, not a provider — its own product,
with its own CLI and web UI, where the user configures providers inside it.
Adopting it would mean Marvi talks to LiteLLM, which talks to the provider: an
extra hop, an extra service to supervise, and a second home for provider
configuration. Marvi talks to providers directly. A LiteLLM instance someone
already runs is just another OpenAI-compatible endpoint under **local**.

**A vendor is not a provider.** OpenAI sells an API *and* a Codex plan.
Anthropic sells an API *and* Claude Code. Different endpoints, different auth,
different billing — so different profiles. The registry keys on **how you reach
a model**, never on who made it.

## One source of truth

Every provider lives in **one folder**, `services/gateway/src/marvi_gateway/providers/`,
one module per provider, each exporting a profile and registering itself. Nothing
about a provider appears anywhere else in the codebase.

The hard rule for this phase: **nothing is hardcoded**. Base URLs, model names,
keys, and selections all resolve from environment or config and are editable
from the control center. Today `deliberate.py` has a literal base URL and
`session.py` has another — that is exactly the pattern being removed.

Marvi keeps using LiveKit for the voice session; the registry decides *which*
model that session is built with, so `openai.LLM(...)` gets its parameters from
a profile instead of from constants in the file.

## The profile

Adapted from the reference implementation's shape, which is the right one:

```
name, aliases                     identity, and the names users actually type
display_name, description         for the picker
signup_url                        where to go to get access
access_path                       api | plan | local
auth_type                         api_key | oauth_device_code | oauth_external | none
env_vars, base_url, models_url    resolved from config, never literal
api_mode                          chat_completions | responses | anthropic
supports_vision                   capability flags that change behaviour
supports_prompt_cache_key
default_aux_model                 the cheap model this provider already has
default_vision_model
fallback_models
limits                            the billing structure (below)
default_headers, fixed_temperature, default_max_tokens
prepare_messages(), build_extra_body(), fetch_models()
```

`default_aux_model` on the profile is why auxiliary models need no router: each
provider already knows which of its own models is the cheap one. Pick a
provider and the auxiliary model comes with it.

## Access paths and their billing structures

Researched per provider, because they genuinely differ.

### API — pay-as-you-go, credit-denominated

Show **remaining credit** where the provider exposes it, and token usage always.

| Provider | Auth | Base URL | Notes |
|---|---|---|---|
| OpenRouter | `api_key` | `openrouter.ai/api/v1` | exposes credit and per-request cost |
| DeepInfra | `api_key` | `api.deepinfra.com/v1/openai` | OpenAI-compatible |
| DeepSeek | `api_key` | `api.deepseek.com` | |
| OpenAI | `api_key` | `api.openai.com/v1` | distinct from Codex below |
| Anthropic | `api_key` | `api.anthropic.com` | `anthropic` api_mode, not chat_completions |
| **OpenCode Zen** | `api_key` | `opencode.ai/zen/v1` | **pay-as-you-go**, credit-based |

### Plan — subscriptions with rolling windows

Not credit. Rolling usage windows that reset, and the window shape differs per
vendor. Show the limits where they can be obtained.

| Provider | Auth | Limit structure |
|---|---|---|
| **OpenCode Go** | `api_key` | **three rolling windows: $12 / 5h, $30 / week, $60 / month** — dollar-denominated but plan-capped, usage visible only in their console |
| Codex | `oauth_external` (`auth.openai.com/oauth/token`) | rolling window tied to the ChatGPT plan; exhaustion surfaces as **429 with `Retry-After`** |
| Claude Code | `oauth_external` | 5-hour session window plus a weekly cap |
| GitHub Copilot | token exchange from a GitHub token | seat-based |
| Qwen | `oauth_external` (`chat.qwen.ai/api/v1/oauth2/token`) | portal account |
| xAI, Nous | `oauth_device_code` | device-code flow |
| Alibaba, Kimi coding plans | mixed | monthly vendor plans |

**Zen and Go are different providers, not one with a flag.** Zen is
pay-as-you-go against credit; Go is a $10/month plan with rolling caps. They
have different base URLs (`/zen/v1` vs `/zen/go/v1`), different billing, and
different failure modes.

### Local — free, private, offline-capable

| Provider | Auth | Endpoint |
|---|---|---|
| Ollama | `none` | `http://localhost:11434/v1` |
| LM Studio | `none` | `http://localhost:1234/v1` |
| llama.cpp / vLLM | `none` | user-configured |

One `local` profile with a configurable base URL and named presets covers all of
them. These are the only providers that keep working with the network down and
the only ones with no privacy question, which makes local the natural home for
auxiliary work.

## Budget control is always in tokens

This is the decision that makes the rest coherent.

Credit, dollar caps, rolling windows and seats cannot be compared, and most of
them **cannot be read back at all** — OpenCode Go publishes no usage header and
shows consumption only in its own console. Any guard built on provider-reported
spend would silently stop working on exactly the plans it most needs to guard.

So: **Marvi counts tokens locally, and the budget in `REAL-AGENCY.md` is
denominated in tokens.** Tokens are reported in every response, are identical
across all three access paths, need no network call to check, and cannot be
wrong because a provider changed its pricing page.

Money and limits become **display**, not control:

- **API providers** — show remaining credit where exposed, plus token usage.
- **Plans** — show the window and how close it is, where obtainable. For Go that
  is the 5-hour / weekly / monthly caps; for Codex it is what the 429
  `Retry-After` tells us. Where nothing is exposed, show local token counts and
  say plainly that the provider does not publish usage.
- **Local** — tokens only. Nothing to spend.

A 429 with `Retry-After` is treated as a **window exhaustion signal**: cool that
provider down until the reset and fail over, rather than retrying into a wall.

## What this unblocks

- **Phase 8's missing VLM.** `supports_vision` and `default_vision_model` turn
  "OpenCode Go has no vision model" into provider selection. `describe.py`
  already speaks the right shape and needs no change.
- **Real failover.** The case that actually happens is a plan hitting its
  5-hour window mid-afternoon. Cooldown plus `fallback_models` keeps working.
- **One boundary for two callers.** Until `session.py` and `deliberate.py` share
  the registry, a second provider only works in half the app.

## Identity — `SOUL.md` and `USER.md`

Short files, and every implementation of this convention agrees on that: roughly
0.5 KB and 1.3 KB in the reference, against a 4 KB memory file. `AGENTS.md`
already requires the voice prompt to stay small, and every token here is paid on
every turn.

- **`SOUL.md`** — who Marvi is: voice, temperament, what it refuses. Authored by
  the user; never written by Marvi.
- **`USER.md`** — who the user is: name, pronouns, hours, standing preferences.
  Marvi may *propose* additions through the confirmation flow, never edit
  silently, or the persona becomes self-modifying and unauditable.
- **Memory stays separate.** `USER.md` is what is true on every turn; memory is
  what happened. Relevant only sometimes means memory.

The composer is a tested function with a token budget and a defined truncation
order. **The trust boundary must not blur**: identity files are user-authored
and may shape behaviour; anything recalled from memory, an account, or the web
keeps its envelope (ADR-015).

## Work breakdown

**Step 1 — foundation. Done.** `providers/` package with the profile dataclass,
registry, alias lookup, and the four things that actually differ between
providers: API shape (`chat_completions` / `responses` / `anthropic`),
streaming, reasoning effort, and prompt caching. Cache-aware `Usage` separates
`cached_input` so the budget can see what caching saves. Local providers
(Ollama, LM Studio, llama.cpp/vLLM) and both OpenCode providers are registered;
Zen and Go are separate profiles. 36 tests. See `docs/PROVIDERS.md`.

**Step 2 — move the callers.** `session.py` and `deliberate.py` resolve through
the registry; their hardcoded base URLs are deleted. This is the step that makes
every later provider work everywhere at once.

**Step 3 — token accounting.** Record `Usage` per call, make the
`REAL-AGENCY.md` budget bind on `billable` tokens, and prove caching reduces it.

**Step 4 — more API providers.** OpenRouter, DeepInfra, DeepSeek: profiles only,
no new machinery.

**Step 5 — the other API shapes.** OpenAI Responses and Anthropic Messages, with
a live call against each. The shapes are built and tested; this proves them.

**Step 6 — OAuth.** One plan provider end to end — acquisition, refresh ahead of
expiry, an explicit expired state, and a storage decision for refresh tokens.
Then the rest.

**Step 7 — limits and cooldown.** Display credit and window state; treat 429 +
`Retry-After` as window exhaustion and fail over.
**Step 8 — providers page.** Connect, disconnect, reconnect; model per job;
credit, window and token usage. Everything editable, nothing in code.

**Step 9 — identity files and composer**, with the editor surface.

## Acceptance evidence required

- One provider from each access path working: API, plan over OAuth without
  Marvi handling a password, and local.
- The same vendor on both paths at once — the OpenAI API and Codex — selectable
  and accounted independently.
- A local provider still answering with the network unavailable.
- Token budget binds identically on an API provider, a plan, and a local model.
- A 429 with `Retry-After` cools that provider down and fails over rather than
  retrying.
- An expired token surfaces as "reconnect", and reconnecting restores service
  without a restart.
- No base URL, model name, or key literal remains in application code; changing
  a provider in the GUI takes effect without an edit.
- `SOUL.md` and `USER.md` change behaviour within the prompt budget, and the
  Phase 5 injection tests still pass with identity loaded.

## Risks and open questions

- **Plan terms.** Driving a coding-plan subscription from an ambient assistant
  may fall outside what that plan permits. This needs checking per provider
  before shipping — it is a terms question, not a technical one.
- **OAuth flows are bespoke and change.** Prove one end to end, including
  refresh and revocation, before adding more.
- **Refresh tokens at rest are credentials**, and need a storage decision rather
  than a default JSON file.
- **Most plans publish no usage.** Local token counting is an estimate of
  position within a window, not the provider's own number, and the UI must not
  imply otherwise.
- **Prompt bloat** on the voice path Phase 3 tuned hard. The budget is enforced
  in code, not by intention.
