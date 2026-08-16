# Providers

Every provider Marvi can reach lives in one place:
`services/gateway/src/marvi_gateway/providers/`, one module each. Adding a
provider means adding a module there and nothing else.

**No base URL, model name, or key appears in application code.** Everything
resolves from environment variables through the profile, so it stays editable
from the control center without a rebuild.

## Status

| Provider | Path | Auth | API shape | Status |
|---|---|---|---|---|
| Ollama | local | none | chat completions | **implemented** |
| LM Studio | local | none | chat completions | **implemented** |
| llama.cpp / vLLM | local | none | chat completions | **implemented** |
| OpenCode Zen | api | api key | chat completions | **implemented** |
| OpenCode Go | plan | api key | chat completions | **implemented** |
| OpenAI | api | api key | chat completions | **implemented** |
| OpenAI (Responses) | api | api key | responses | **implemented** |
| Anthropic | api | api key | messages | **implemented** |
| Codex | plan | `oauth_external` | responses | **profile ready, OAuth pending** |
| Claude Code | plan | `oauth_external` | messages | **profile ready, OAuth pending** |
| OpenRouter | api | api key | chat completions | planned |
| DeepInfra | api | api key | chat completions | planned |
| DeepSeek | api | api key | chat completions | planned |
| GitHub Copilot | plan | token exchange | chat completions | planned |
| Qwen | plan | `oauth_external` | chat completions | planned |
| xAI, Nous | api/plan | `oauth_device_code` | chat completions | planned |
| Alibaba, Kimi coding plans | plan | mixed | chat completions | planned |

## Implemented

### Local — Ollama, LM Studio, llama.cpp, vLLM

All four serve an OpenAI-compatible chat completions API, so they are one shape
with different default ports rather than four plugins.

They matter more than their size suggests: they are the only providers that keep
working with the network down, the only ones with no privacy question, and the
only ones that cost nothing. That makes local the default choice when several
providers are configured, and the right home for auxiliary work.

| | Ollama | LM Studio | llama.cpp / vLLM |
|---|---|---|---|
| URL env | `MARVI_OLLAMA_URL` | `MARVI_LMSTUDIO_URL` | `MARVI_LOCAL_OPENAI_URL` |
| default | `localhost:11434/v1` | `localhost:1234/v1` | none — must be set |
| model env | `MARVI_OLLAMA_MODEL` | `MARVI_LMSTUDIO_MODEL` | `MARVI_LOCAL_OPENAI_MODEL` |

**Needs:** the server running. Nothing else.

**Caching:** none requested. These servers keep their own KV cache across
requests sharing a prefix, but there is nothing to ask for in the request. A
local token is free either way.

### OpenCode Zen — pay-as-you-go

`OPENCODE_ZEN_API_KEY`, `https://opencode.ai/zen/v1`. Billed against credit.
Credit balance is shown in the OpenCode console, not over the API.

### OpenCode Go — subscription plan

`OPENCODE_GO_API_KEY`, `https://opencode.ai/zen/go/v1`. $10/month with **three
rolling caps: $12 per 5 hours, $30 per week, $60 per month.**

Zen and Go are **separate providers, not one with a flag**. Different base URL,
different billing, different failure modes. Collapsing them would leave the UI
unable to say which limit you are about to hit.

Neither publishes usage over the API, so Marvi shows its own token count and
says so.

### OpenAI and Anthropic

`OPENAI_API_KEY` and `ANTHROPIC_API_KEY`. OpenAI is registered twice — once for
chat completions and once for the Responses API — because they are different
wire formats and the reasoning path wants Responses.

Their caching differs in a way that matters. **OpenAI caches automatically**
above a minimum prefix length; `prompt_cache_key` only makes routing sticky so
the same prefix lands on the same backend. **Anthropic caches nothing unless
asked** — a prefix is only cached if marked with a `cache_control` breakpoint,
and forgetting the mark costs full price silently on every turn. Marvi marks it
by default.

### Codex and Claude Code — profiles ready, OAuth pending

Both profiles exist with the right API shape, models, and window structure. They
cannot be used until the OAuth flow lands; the access token env vars are
placeholders that the flow will populate rather than values to type in.

## Calling, accounting, and cooldown

One client (`providers/client.py`) executes every call, which is why three
things fall out of one implementation:

- **Token accounting** — usage recorded per provider in its own shape and
  normalised, so the budget binds identically on an API, a plan, and a local
  model. `usage_by_provider()` is what the page displays.
- **Cooldown** — a 429 with `Retry-After` stands the provider down until its
  window resets. Retrying into an exhausted plan is how one bad afternoon turns
  into a quota-burning loop. A rejected credential cools down for six hours,
  because a dead key will not fix itself.
- **Failover** — `call_with_fallback` walks configured providers, local first.
  Anything that fails is already resting, so the next attempt does not return
  to it.

Streaming is deliberately not implemented here: the voice path streams through
LiveKit's client, which already owns interruption and playout. This client
serves the background mind, where nobody is waiting on a first token.

## Plan terms

Subscription plans are sold for interactive use, and driving one from an
always-on assistant may fall outside their terms. Marvi does **not** block this —
it is the user's account and their decision, and other agent tools work the same
way — but it shows a warning once before connecting a plan provider, naming the
real risk: account suspension, not a warning email.

## Planned, and what each one needs

| Provider | Needs before it can be added |
|---|---|
| OpenRouter, DeepInfra, DeepSeek | an API key; all OpenAI-compatible, so the profile is the whole job |
| OpenAI | a key; plus Responses-API support if used for reasoning models |
| Anthropic | a key; `messages` shape and explicit cache breakpoints |
| Codex | OAuth against `auth.openai.com/oauth/token`, token storage and refresh, and the Responses shape |
| Claude Code | OAuth, plus the 5-hour and weekly window display |
| GitHub Copilot | token exchange from a GitHub token, and seat verification |
| Qwen | OAuth against `chat.qwen.ai/api/v1/oauth2/token` |
| xAI, Nous | device-code flow with polling |

**Open question for every plan provider:** whether driving a coding-plan
subscription from an ambient assistant is within that plan's terms. This is a
terms question, not a technical one, and should be answered per provider before
that provider ships.

## The profile

Providers differ in four ways that change the request itself, which is why this
is a real abstraction and not a URL plus a key.

### 1. API shape — `api_mode`

Three wire formats, not three URLs:

| Mode | Endpoint | System prompt | Token limit field |
|---|---|---|---|
| `chat_completions` | `/chat/completions` | a message with `role: system` | `max_tokens` |
| `responses` | `/responses` | inside `input` | `max_output_tokens` |
| `anthropic` | `/v1/messages` | a separate `system` block | `max_tokens` (required) |

Anthropic also authenticates with `x-api-key` and an `anthropic-version` header
rather than a bearer token.

### 2. Streaming

The voice path needs tokens as they arrive; background deliberation does not.
When streaming a `chat_completions` provider, Marvi sends
`stream_options: {include_usage: true}` — without it many OpenAI-compatible
servers omit usage entirely on streamed responses and the token budget goes
blind.

### 3. Reasoning effort

Three incompatible conventions, so the profile declares which one applies and
the caller never guesses:

- **`none`** — the effort argument is dropped.
- **`effort`** — `reasoning_effort: low|medium|high`. An unsupported value falls
  back to the provider's default rather than erroring.
- **`budget_tokens`** — Anthropic's `thinking: {type: enabled, budget_tokens: N}`.

### 4. Prompt caching — the cost lever

This is what makes Marvi affordable, and it is why the budget is denominated in
tokens rather than money.

The system prompt, identity files, and tool schemas are **identical on every
turn**. Paying full price for them each time is pure waste. A cached input token
costs a fraction of a fresh one, so caching directly reduces the number that the
budget guard counts.

| Style | How | Used by |
|---|---|---|
| `none` | nothing sent | local providers |
| `cache_key` | `prompt_cache_key`, stable across turns | OpenAI-compatible, OpenCode |
| `explicit_breakpoints` | `cache_control: {type: ephemeral}` on a content block | Anthropic |
| `automatic` | provider caches without being asked | some vendors |

`Usage` separates `cached_input` from `input` precisely so this is visible:

```
uncached   1000 in + 50 out  ->  1050 billable
cached      900 of 1000 hit  ->   150 billable
```

Same work, a seventh of the billed tokens. `Usage.billable` is what the budget
sees.

## Budget control

**Always tokens.** Credit, dollar caps, seats and rolling windows cannot be
compared, and most cannot be read back — OpenCode Go publishes usage only in its
console. A guard built on provider-reported spend would silently stop working on
exactly the plans it most needs to guard.

Tokens are reported in every response, identical across all three access paths,
need no network call, and cannot go stale when a pricing page changes.

Money and limits are **display**: credit where a provider exposes it, window
state where obtainable, and an honest "this provider does not publish usage"
where it does not.

A `429` with `Retry-After` is treated as **window exhaustion**: cool that
provider down until reset and fail over, rather than retrying into a wall.

## Adding a provider

1. Create `providers/<name>.py`, build a `ProviderProfile`, call `register()`.
2. Import it in `providers/__init__.py`.
3. Add a row to the status table above.
4. Only register it once it actually works — the table is the contract.
