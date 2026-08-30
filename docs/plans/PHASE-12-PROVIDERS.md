# Phase 12 — Providers, models, and reasoning effort

**Implementation note (2026-08-31):** the per-model effort correction in this
plan is now implemented in the existing shared catalog and request builder.
Provider/model separation and follow-main routing were already implemented by
the earlier Phase 12 milestones; this correction adds live capability parsing,
the packaged fallback table, native request mapping, Off presentation, and
durable credential disconnect tombstones.

Third attempt. The previous two produced a Providers page that mixes connecting
an account with choosing a model, an `aux` model that is a string on a provider
profile rather than a decision, and a model list that is hardcoded because
nothing ever fetched one. This plan is written before the code because writing
it is what the previous attempts skipped.

## What is wrong today

`ProviderProfile` carries `default_model`, `default_aux_model` and
`default_vision_model` as strings, and `model_for(job)` picks between them. So:

- **A model is a property of a provider.** It is not. It is a choice the user
  makes *within* a provider, and it changes far more often than the provider
  does.
- **Nothing fetches a model list.** `models_path = "/models"` exists on the
  profile and no caller uses it. Every model name in the app is a literal in
  the registry.
- **Auxiliary is a second literal.** There is no notion of "follow the main
  model", which is what a user means by a default.
- **Reasoning effort exists and is out of date.** I wrote "does not exist,
  no field, no request shaping" in the first draft of this plan and was wrong.
  `base.py` has `ReasoningPolicy` with `style`, `levels`, `default` and a
  `normalise()` that clamps to what a provider accepts — the right shape. But
  both Anthropic profiles use `style="budget_tokens"`, and `build_request`
  emits `{"thinking": {"type": "enabled", "budget_tokens": ...}}`, which is
  deprecated on Claude 4.6 and **rejected with a 400 on 4.7 and later**. So the
  work is not building it; the work is `adaptive` + `effort`, and deleting the
  `budget_tokens` style rather than extending it.
- **Nothing streams.** `ProviderClient.call` hardcodes `stream=False`, so chat
  waits for a whole response before showing a word. First-token latency is not
  a voice-only concern: the streaming endpoint Phase 12 needs for voice is the
  same one that makes chat feel immediate.

## Research

### Reference implementation

Three things worth taking, and worth taking the reasons with them.

**The predecessor's provider catalog — one catalog behind every surface.** Its
docstring is a post-mortem: the CLI picker and two desktop tabs each read a
different hand-maintained list, so "every provider added after those lists were
written silently went missing from the GUI". The fix derives one descriptor per
provider from a single universe, and a **parity contract locked by tests** keeps
the surfaces honest. Marvi has one registry today and must not grow a second
list for a Models page.

**`auth_type` decides the surface.** The catalog routes a provider to its Accounts
tab or its API-keys tab purely by how the provider authenticates. Marvi's
`ProviderProfile.auth_type` already carries that, so the Providers page can
split on it without new data.

**`agent/auxiliary_client.py` — auxiliary is a router, not a model.** It is a
resolution chain for side tasks — compression, search, extraction, vision —
whose first step is *the user's main provider and main model*, with fallbacks
after it. That is exactly "auxiliary follows main by default", implemented as a
reference rather than a copy.

**`agent/lmstudio_reasoning.py` — clamp, and prefer omission.** It maps a
generic effort ladder onto one provider's vocabulary, clamps against the
model's published `allowed_options`, and returns `None` — meaning *omit the
field* — when the user asked for a level the model cannot honour, "rather than
silently substituting a different effort". It also keeps its alias table and
its clamp table separate, because one of them is applied to the model's
published options and must not rewrite them.

### The provider APIs, as of August 2026

**Listing models.** The endpoint and the response shape both differ:

| Provider | Endpoint | Capabilities in the response? |
|---|---|---|
| OpenAI and compatible | `GET /v1/models` | **No** — `id`, `object`, `created`, `owned_by` only |
| Anthropic | `GET /v1/models` | **Yes** — `capabilities.effort` and `capabilities.thinking` |
| OpenRouter | `GET /api/v1/models` | **Yes** — per-model `reasoning.supported_efforts` and `mandatory` (with `supported_parameters` retained as a legacy signal) |
| LM Studio | `GET /api/v1/models` | **Yes** — `capabilities.reasoning.allowed_options` |
| Ollama | `GET /api/tags`, or `/v1/models` in compat mode | Yes — a thinking capability flag |

**Reasoning effort.** Four incompatible shapes:

| Provider | Field | Levels |
|---|---|---|
| OpenAI chat completions | `reasoning_effort` | `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` — *model-dependent subset* |
| OpenAI responses | `reasoning.effort` | as above |
| Anthropic ≤ 4.5 | `thinking.type="enabled"` with `budget_tokens` | an integer token budget |
| Anthropic 4.6 | either; `budget_tokens` deprecated | `low`, `medium`, `high`, `max` |
| Anthropic ≥ 4.7 | `thinking.type="adaptive"` with `effort` | `budget_tokens` is **rejected with a 400** |
| LM Studio | `reasoning_effort` | whatever the model publishes in `allowed_options` |
| Ollama | `think` natively; compatible effort fields on `/v1` | boolean for most thinking models; `low`/`medium`/`high` for GPT-OSS |

Two conclusions follow, and they are the load-bearing ones:

1. **Effort is not a shared vocabulary.** One `low|medium|high` dropdown sent
   verbatim to every provider is wrong for four of the six. Marvi needs a
   generic ladder plus a per-provider mapping.
2. **Support is discoverable for some providers and not others.** OpenRouter,
   Anthropic, and LM Studio publish exact model metadata. OpenAI does not, and
   Ollama's compatibility list is partial, so "fetch when possible, hide
   otherwise" needs a fallback table. That table is packaged data, not code.

Two things I told the user earlier were wrong, and the record should say so: I
described reasoning effort as "fixed levels like low/medium/high" when OpenAI
takes seven and the supported subset is per-model, and I said "most local
servers do not" expose effort when LM Studio and Ollama both do.

## The shape

### 1. Separate the provider from the model

`ProviderProfile` keeps identity, credentials, endpoint, API mode and limits. It
**loses** `default_model`, `default_aux_model` and `default_vision_model`.

A `ModelChoice` store holds what the user picked:

    main:    {provider, model, effort}
    aux:     {follows_main: true} | {provider, model, effort}
    vision:  {follows_main: true} | {provider, model, effort}

`follows_main` is the default and is a real state rather than a copied string,
so a change to main is felt everywhere that follows it. That is what a user
means by a default.

### 2. Fetch the model list

A new `providers/models.py`:

- `list_models(profile) -> list[ModelInfo]`, with one adapter per API shape,
  chosen by `api_mode` rather than by provider name.
- `ModelInfo = {id, label, reasoning: EffortSupport | None}`.
- Cached on disk with a TTL. A dropdown must not wait on a network call, and a
  provider must not be polled on every render. Stale-while-revalidate: show
  what is cached, refresh behind it.
- **A failed fetch is reported as a failed fetch.** It does not fall back to a
  hardcoded list, because a list that quietly lies about what a provider offers
  is how the present state came about.

### 3. Effort, mapped rather than assumed

A new `providers/effort.py`:

- One generic ladder: `off`, `low`, `medium`, `high`, `max`.
- `supported_efforts(profile, model) -> list[str] | None` — from the fetched
  capability where the provider publishes one, from
  `config/model-capabilities.json` where it does not, and `None` when nothing
  is known.
- `apply_effort(request, profile, model, effort)` shapes the request per
  `api_mode`: `reasoning_effort`, `reasoning.effort`, `thinking.adaptive` with
  `effort`, or `think`. **Never `budget_tokens`** — deprecated on 4.6 and a 400
  on 4.7, so Marvi will not emit it at all.
- Omit rather than substitute when a level is not supported.

### 4. The surfaces

**Providers page** — connect only. Credential or OAuth, reachability, limits,
usage. No model selection at all.

**Models page** — a provider dropdown listing only connected providers, then a
model dropdown fetched from that provider, then an effort dropdown shown only
where the model supports one. Three rows: main, auxiliary, vision, with
auxiliary and vision starting as "follow main".

**Chat composer** — a small model selector that overrides for that session
only, and says so. It writes to session state, never to the stored choice.

## Order of work

1. `models.py`: fetch adapters and the cache, with tests against recorded
   fixtures of each response shape.
2. `effort.py`: the ladder, the mapping and the omit rule, with a test that
   asserts `budget_tokens` is never emitted.
3. The `ModelChoice` store and `follows_main` resolution.
4. Strip the model fields from `ProviderProfile` and fix every caller.
5. Providers page down to connect-only.
6. Models page.
7. Session override in the composer.

Steps 1 to 4 are the engine and can land together. Steps 5 to 7 are the surface
and are worth a separate release, so a break is attributable to one of them.

## What would make this attempt fail

- A second list of providers or models anywhere. One registry, one catalog, and
  a test that says so — this class of drift is expensive to rediscover.
- Sending a generic effort string straight through to a provider.
- A model dropdown backed by a hardcoded array because the fetch was
  "temporarily" stubbed.
- Treating auxiliary as a copy of main rather than a reference to it.

## Sources

- [OpenAI reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)
- [`/v1/models` has no capabilities field](https://community.openai.com/t/expose-model-capabilities-in-the-v1-models-api-response/1314117)
- [Anthropic adaptive thinking](https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking)
- [Anthropic extended thinking and its deprecation](https://platform.claude.com/docs/en/build-with-claude/extended-thinking)
- [OpenRouter models and `supported_parameters`](https://openrouter.ai/docs/guides/overview/models)
- [LM Studio OpenAI-compatible endpoints](https://lmstudio.ai/blog/lmstudio-v0.3.29)
- [Ollama API reference](https://deepwiki.com/ollama/ollama/3-api-reference)
