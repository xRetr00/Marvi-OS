# Providers

Every provider Marvi can reach lives in one place:
`services/gateway/src/marvi_gateway/providers/`, one module each. Adding a
provider means adding a module there and nothing else.

**No base URL, model name, or key appears in application code.** Everything
resolves from environment variables through the profile, so it stays editable
from the control center without a rebuild.

## Status

| Provider                   | Path     | Auth                | API shape        | Status                             |
| -------------------------- | -------- | ------------------- | ---------------- | ---------------------------------- |
| Ollama                     | local    | none                | chat completions | **implemented**                    |
| LM Studio                  | local    | none                | chat completions | **implemented**                    |
| llama.cpp / vLLM           | local    | none                | chat completions | **implemented**                    |
| OpenCode Zen               | api      | api key             | chat completions | **implemented**                    |
| OpenCode Go                | plan     | api key             | chat completions | **implemented**                    |
| OpenAI                     | api      | api key             | chat completions | **implemented**                    |
| OpenAI (Responses)         | api      | api key             | responses        | **implemented**                    |
| Anthropic                  | api      | api key             | messages         | **implemented**                    |
| Codex                      | plan     | `oauth_external`    | responses        | **implemented, needs a client ID** |
| Claude Code                | plan     | `oauth_external`    | messages         | **implemented, needs a client ID** |
| OpenRouter                 | api      | api key             | chat completions | **implemented**                    |
| DeepInfra                  | api      | api key             | chat completions | **implemented**                    |
| DeepSeek                   | api      | api key             | chat completions | **implemented**                    |
| GitHub Copilot             | plan     | token exchange      | chat completions | planned                            |
| Qwen                       | plan     | `oauth_external`    | chat completions | planned                            |
| xAI, Nous                  | api/plan | `oauth_device_code` | chat completions | planned                            |
| Alibaba, Kimi coding plans | plan     | mixed               | chat completions | planned                            |

## Implemented

### Local — Ollama, LM Studio, llama.cpp, vLLM

All four serve an OpenAI-compatible chat completions API, so they are one shape
with different default ports rather than four plugins.

They matter more than their size suggests: they are the only providers that keep
working with the network down, the only ones with no privacy question, and the
only ones that cost nothing. That makes local the default choice when several
providers are configured, and the right home for auxiliary work.

|           | Ollama               | LM Studio              | llama.cpp / vLLM           |
| --------- | -------------------- | ---------------------- | -------------------------- |
| URL env   | `MARVI_OLLAMA_URL`   | `MARVI_LMSTUDIO_URL`   | `MARVI_LOCAL_OPENAI_URL`   |
| default   | `localhost:11434/v1` | `localhost:1234/v1`    | none — must be set         |
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

Requests to both OpenCode paths identify the public app as **Marvi** at
`https://marvi-alpha.vercel.app/` through the supported `HTTP-Referer` /
`X-Title` headers.

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

### OpenRouter, DeepInfra, DeepSeek

Three metered, OpenAI-compatible APIs that needed no new machinery — with the
client in place, a provider is now genuinely just a profile.

`OPENROUTER_API_KEY`, `DEEPINFRA_API_KEY`, `DEEPSEEK_API_KEY`.

OpenRouter requests include its documented app-attribution headers:
`HTTP-Referer: https://marvi-alpha.vercel.app/` and
`X-OpenRouter-Title: Marvi`. The Gateway profile owns these values and passes
them to the direct LiveKit voice path as non-secret request metadata, so chat,
background, catalog, and voice calls do not drift. DeepInfra and DeepSeek do
not document an equivalent app-name/site attribution pair, so Marvi does not
invent one for them.

Three are worth knowing about. **OpenRouter publishes per-key spend and limits**
at `GET /api/v1/key`; **DeepSeek publishes account balances** at
`GET /user/balance`; and **DeepInfra publishes monthly billing usage** at
`GET /payment/usage`. These values appear on Usage, explicitly separated from
Marvi's own request ledger. **DeepSeek reports its cache differently**: no
`prompt_tokens_details`, but `prompt_cache_hit_tokens` and
`prompt_cache_miss_tokens` instead. Reading only the OpenAI shape would bill
every cached token as fresh on the provider that caches hardest, so `read_usage`
understands both.

### Codex and Claude Code — OAuth

Both work, and both need one thing from you first: **the vendor's client ID**,
in `MARVI_CODEX_CLIENT_ID` or `MARVI_CLAUDE_CODE_CLIENT_ID`.

Marvi does not ship those values. They belong to OpenAI and Anthropic, they are
rotated at the vendor's discretion, and a hardcoded one would fail silently
months later with no clue why. The Providers page says which variable is missing
rather than offering a Sign In button that cannot work.

## How the OAuth flow works

Authorization code with PKCE, and the reason for each piece:

- **Marvi never sees your password.** You sign in on the provider's own page, in
  your own browser. Marvi hands the desktop app a URL and receives only the
  redirect. There is no field in Marvi to type a provider password into, by
  design and not by omission.
- **PKCE always.** The redirect lands on `http://localhost:<port>`, which any
  local process could try to race for. The verifier never leaves the Gateway, so
  a stolen authorization code is worth nothing on its own.
- **`state` is verified, not merely sent.** Without that check, another page in
  your browser could hand Marvi a code for an account you did not choose.
- **The listener answers one request and dies.** A loopback server left running
  is a way in.
- **Refresh happens ahead of expiry**, not after a failure — a token that dies
  mid-call is a lost turn, and on the voice path that is an audible stall. A
  refresh response that omits the refresh token means "keep the one you have",
  and dropping it would quietly turn a lasting connection into a one-hour one.

### Where tokens are stored

**Windows: DPAPI, scoped to your user account.** `CryptProtectData` encrypts
with a key derived from the logged-in account, so `tokens.bin` is useless to
another account on the machine and useless if copied off it. No password prompt,
no keyring service, no new dependency.

On other platforms the file falls back to owner-only permissions, and Marvi says
so rather than implying encryption. Marvi is Windows-first; that path exists for
development.

Tokens deliberately do **not** go into `providers.env` beside the API keys. That
file is read and written by the settings GUI; a refresh token is not a setting.

A store that cannot be read — written by a different Windows account, or
truncated — reports "reconnect" rather than preventing the Gateway from
starting.

## Calling, accounting, and cooldown

One client (`providers/client.py`) executes every call, which is why three
things fall out of one implementation:

- **Token accounting** — usage recorded per provider in its own shape,
  normalised, and atomically persisted to `%LOCALAPPDATA%\Marvi-OS\usage.json`.
  The file contains UTC dates and counters only; never prompts or responses.
- **Cooldown** — a 429 with `Retry-After` stands the provider down until its
  window resets. Retrying into an exhausted plan is how one bad afternoon turns
  into a quota-burning loop. A rejected credential cools down for six hours,
  because a dead key will not fix itself.
- **Failover** — `call_with_fallback` walks configured providers, local first.
  Anything that fails is already resting, so the next attempt does not return
  to it.

Voice streams through LiveKit's client, which owns interruption and playout.
Because that direct low-latency path bypasses `ProviderClient`, LiveKit's
cumulative `session_usage_updated` values are sent to the Gateway as deltas.
Each voice turn therefore reaches the same durable ledger exactly once.

## Chat and voice are one Marvi

Both surfaces resolve through this registry, and both run tools through the same
router with the same confirmation flow. Chat has no private door: a sensitive
action typed into it pauses for approval exactly as one spoken aloud does, and
resolves the same token. Tool results re-enter the conversation inside their
untrusted envelope, because a tool can return text somebody else wrote.

The only difference is transport. Voice streams through LiveKit's client, which
owns interruption and playout; chat calls `ProviderClient` directly, where
nobody is waiting on a first token.

## Where settings live

The registry reads `os.environ` and nothing else. The control center edits
`%LOCALAPPDATA%\Marvi OS\providers.env`, which is loaded into the environment
when the Gateway starts and applied immediately on save — so there is still one
source of truth, and the GUI edits the thing that fills it.

A variable already set in the real environment **wins** over the saved file, so
launching with `OPENAI_API_KEY=...` in the shell is not silently overridden by a
stale saved value. Clearing a value in the GUI is how you disconnect.

Credentials are masked on the way out (`…3f9a`) and never written to the audit
log; what is recorded is that a setting changed, not what it changed to.

## Who resolves the provider

Everything resolves in the Gateway. The Agent worker runs in its own Python
environment and asks `GET /providers/voice` at startup rather than carrying a
second copy of the provider table — two copies drift, and the one that drifts is
always the one the user did not edit.

That endpoint only offers a **chat-completions** provider, because the LiveKit
OpenAI plugin cannot speak Anthropic's Messages API, and only one that actually
answers: a local server counts as "configured" the moment it has a default URL,
which is not the same as something listening on it.

## Plan terms

Subscription plans are sold for interactive use, and driving one from an
always-on assistant may fall outside their terms. Marvi does **not** block this —
it is the user's account and their decision, and other agent tools work the same
way — but it shows a warning once before connecting a plan provider, naming the
real risk: account suspension, not a warning email.

## Planned, and what each one needs

| Provider                        | Needs before it can be added                                                                    |
| ------------------------------- | ----------------------------------------------------------------------------------------------- |
| OpenRouter, DeepInfra, DeepSeek | an API key; all OpenAI-compatible, so the profile is the whole job                              |
| OpenAI                          | a key; plus Responses-API support if used for reasoning models                                  |
| Anthropic                       | a key; `messages` shape and explicit cache breakpoints                                          |
| Codex                           | OAuth against `auth.openai.com/oauth/token`, token storage and refresh, and the Responses shape |
| Claude Code                     | OAuth, plus the 5-hour and weekly window display                                                |
| GitHub Copilot                  | token exchange from a GitHub token, and seat verification                                       |
| Qwen                            | OAuth against `chat.qwen.ai/api/v1/oauth2/token`                                                |
| xAI, Nous                       | device-code flow with polling                                                                   |

**Open question for every plan provider:** whether driving a coding-plan
subscription from an ambient assistant is within that plan's terms. This is a
terms question, not a technical one, and should be answered per provider before
that provider ships.

## The profile

Providers differ in four ways that change the request itself, which is why this
is a real abstraction and not a URL plus a key.

### 1. API shape — `api_mode`

Three wire formats, not three URLs:

| Mode               | Endpoint            | System prompt                 | Token limit field       |
| ------------------ | ------------------- | ----------------------------- | ----------------------- |
| `chat_completions` | `/chat/completions` | a message with `role: system` | `max_tokens`            |
| `responses`        | `/responses`        | inside `input`                | `max_output_tokens`     |
| `anthropic`        | `/v1/messages`      | a separate `system` block     | `max_tokens` (required) |

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

| Style                  | How                                                   | Used by                     |
| ---------------------- | ----------------------------------------------------- | --------------------------- |
| `none`                 | nothing sent                                          | local providers             |
| `cache_key`            | `prompt_cache_key`, stable across turns               | OpenAI-compatible, OpenCode |
| `explicit_breakpoints` | `cache_control: {type: ephemeral}` on a content block | Anthropic                   |
| `automatic`            | provider caches without being asked                   | some vendors                |

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

## Usage sources

The dedicated Usage page is the only usage surface. Providers configures
connections; it does not carry a second set of counters. The page separates:

- **Marvi ledger** — response usage for Chat, background work, local models,
  and voice-session deltas. This is durable, content-free, and limited to work
  this installation performed.
- **Provider account** — optional remote values that can include other clients.
  OpenRouter uses the configured API key. DeepSeek and DeepInfra use their
  configured API keys. OpenAI requires `OPENAI_ADMIN_KEY`; Anthropic requires
  `ANTHROPIC_ADMIN_KEY`. A missing admin key is “unavailable”, never zero.

Official contracts used by the collectors:

- OpenAI organization usage/costs: <https://platform.openai.com/docs/api-reference/usage>
- Anthropic organization reports: <https://docs.anthropic.com/en/api/admin-api/usage-cost/get-messages-usage-report>
- OpenRouter current key: <https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key>
- DeepInfra billing usage: <https://docs.deepinfra.com/api-reference/billing/usage>
- DeepSeek balance: <https://api-docs.deepseek.com/api/get-user-balance>
- Ollama response metrics: <https://docs.ollama.com/api/usage>
- LM Studio compatibility: <https://lmstudio.ai/docs/developer/openai-compat>
- llama.cpp usage object: <https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md>
- OpenCode Go limits: <https://opencode.ai/docs/go/>

Codex, Claude Code, OpenCode Zen, and OpenCode Go do not expose a supported
account-usage API for this integration. Marvi records response tokens and does
not scrape dashboards or mistake a published plan cap for remaining usage.

## Verifying a provider for real

Unit tests check request shaping against recorded payloads. They catch a wrong
field name; they cannot catch a vendor who renamed one or reports usage
differently than their documentation says.

```
uv run --project services/gateway python scripts/verify_provider.py openai
```

One small call per provider — about 30 input tokens, 16 output — checking that
a reply comes back and that usage parses. **It spends money**, which is why it
is a script you run deliberately rather than part of the test suite.

## Adding a provider

1. Create `providers/<name>.py`, build a `ProviderProfile`, call `register()`.
2. Import it in `providers/__init__.py`.
3. Add a row to the status table above.
4. Only register it once it actually works — the table is the contract.
