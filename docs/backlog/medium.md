# Backlog — medium

Extensions of subsystems Marvi already has. **All eleven are built** — seven on
2026-09-16, the last four on 2026-09-18.

| # | Item | State |
|---:|---|---|
| M1 | Long-chat compaction | done |
| M2 | Hooks that can refuse, and more of them | done (refusal is opt-in) |
| M3 | OpenAI-compatible API and ACP agent | endpoint done; ACP agent is its own phase |
| M4 | MCP write access with provenance | done |
| M5 | Image generation | done, with the file contract it needed |
| M6 | Tool-output compression | done |
| M7 | Privacy mode, the whole of it | done |
| M8 | Chat search in the control center | done |
| M9 | Credential pools | done |
| M10 | Replayable runs | done |
| M11 | Focus Assist awareness | done, unconfirmed on this machine |

## Done

### M1. Long-chat compaction

The premise in the original entry was wrong and the fix is better for it. The
window was never unbounded: `_recent` has always kept the last `HISTORY_TURNS`
exchanges, so a long conversation did not overflow the context — it *forgot*.
The twenty-fifth turn could not see the first, and the person could, which is
the version of forgetting that reads as not listening.

So: `Chat.compact` folds whatever has scrolled out into a running summary
(`thread_summaries`), and `_messages` puts it in front of the window as
"Earlier in this conversation: …". It runs *after* a turn, never during one, so
the cost lands where nobody is waiting; a second pass folds into the first
rather than starting again; and a model that fails leaves the conversation
exactly as it was. The stored messages are untouched — compaction is what the
model sees, not what the person's history is, and `chat_search` still finds
every word of it.

`chat.py`, `distil.earlier`, `prompts/conversation-earlier.md`. Tests:
`test_compaction.py`.

### M2. Hooks that can refuse, and more of them

`pre_tool_call` may return `{"action": "block", "message": …}`. The call is
refused with that reason and recorded like any other failure. A granted hook
that *crashes* refuses too — a guardrail that failed
has not consented. It narrows only: confirmation, the room's sleep rule and
every other guard still run, so a hook can never approve anything.

**Blocking is a grant, not a claim.** Installing a plugin does not hand it a
veto over Marvi's tools: it watches until the user names it in
`MARVI_HOOK_GUARDS`, and until then a block it returns is logged once — with
the setting that would allow it — and ignored. Same rule as `register_tool`,
which has always been a request rather than a grant.

Four more events: `pre_turn`, `post_turn`, `on_memory_write`,
`on_confirmation`, raised from the turn, the memory store and the confirmation
store. `hooks.py` holds all of it; the tool router keeps its own set so one
test's handlers never answer for another's.

`hooks.py`, `tools.py`, `plugins.py`, `chat.py`, `memory.py`, `runtime.py`.
Tests: `test_hooks.py`, `test_tool_hooks.py`.

### M4. MCP write access with provenance

`marvi mcp serve` now offers `memory_remember`. What it writes is stored
`trusted=False` with `source = "mcp:<the client's own name>"`, taken from the
MCP session rather than configured — so a fact Claude Code learned is visibly
not a fact Marvi learned, never reaches a prompt as an instruction, and can be
found and removed by its source. It lands on `memory_remember_external`, an
`internal=True` Gateway tool no model is ever offered.

`mcp_serve.py`, `memory.py`. Tests: `test_mcp_serve.py`.

### M7. Privacy mode, the whole of it

One switch, `MARVI_PRIVACY_MODE`, in Settings → Preferences with a PRIVATE
indicator in the status bar next to the confirmation mode. On, it refuses every
tool that reaches the network — web, connected accounts, calendar, email,
Telegram — by name and with the way back, keeps the Telegram bridge from
connecting at all, forces the local memory store over a hosted provider, skips
update checks, and implies `MARVI_LOCAL_ONLY` for every model call. `marvi
doctor` reports it, because a switched-off web search is the most convincing
impersonation of a broken web search there is.

The gate is one place — the tool router — rather than nine handlers. MCP
servers are deliberately *not* gated: they are the user's own installed
processes and Marvi does not know what they do; doctor says exactly that.

`privacy.py`, `tools.py`, `runtime.py`, `telegram.py`, `memory_providers.py`,
`updates.py`, `doctor.py`, `App.tsx`. Tests: `test_privacy.py`.

### M8. Chat search in the control center

The sidebar search box searched thread *titles*, which are auto-named from the
first message and so rarely contain what is being looked for. It now also
searches message text and shows an "IN MESSAGES" group with a snippet per hit;
clicking one opens that conversation.

Behind it, `messages_fts` — external-content FTS5 over `messages` with the same
triggers `memory.py` uses — replaces the LIKE scan, with LIKE kept for queries
FTS5 has no token for (`100%`, `?`). Old databases are backfilled once, tracked
by a marker row rather than a row count: `COUNT(*)` on an external-content FTS5
table reads the *content* table and can never report an empty index.

`chat.py`, `MessageMatches.tsx`, `Sessions.tsx`. Tests: `test_chat_search.py`.

### M9. Credential pools

`OPENROUTER_API_KEY_2` … `_9` (and the same for any provider) are a pool. A 429
or a rejected key moves to the next one and only stands the provider down when
every key is spent — one key's limit is not the provider's limit. A machine
with one key behaves exactly as it did.

`providers/base.py`, `providers/client.py`. Tests: `test_provider_client.py`.

### M6, the half that is real: measurement

The entry's own first step was "measure first", and that is what shipped: every
tool call now records the size of its result in `observations`, so the question
"which tools produce the big results" has an answer drawn from what Marvi
actually did rather than from a guess. Compression itself is deliberately not
built yet — the budgets should come from a week of those rows, not from
intuition, and a cap applied blindly to structured results (`computer_action`,
`browser_action`) breaks tools rather than saving tokens.

## The last four — 2026-09-18

### M3. The endpoint, and why the ACP agent is not here

`POST /v1/chat/completions` and `GET /v1/models`, behind `localauth` on
loopback. Streaming and non-streaming both answer; reasoning is dropped rather
than merged, because a client that cannot tell it from the answer would put a
model's private working in front of a user. `user` names a thread, so two
scripts keep two conversations. `model` is ignored and the docstring says so:
the model is whatever the Models page chose.

Driven end to end with the real `openai` package over a real socket — which is
how the missing `prompts/api.md` was found. Every call through the endpoint had
been raising a 500 from deep inside the turn while the unit tests passed,
because they never got that far. There is now a test for the brief.

**The ACP agent half is deliberately not here.** Being an ACP *client* (which
Marvi is) is answering an agent; being an ACP *agent* is implementing
session/update/permission, deciding what a permission request means when the
approver is an IDE rather than the Island, and qualifying it against a real
editor. That is a phase with its own acceptance gates, not the back half of a
medium item — and pretending otherwise is how a half-implemented protocol ships.

`openai_api.py`, `app.py`, `prompts/api.md`. Tests: `test_openai_api.py`.

### M5. Image generation, and the contract under it

The blocker was real and is now gone. A tool can hand back a file:

    {"produced": {"name": ..., "media_type": ..., "data": <base64>}}

and `chat._keep_produced` — which knows the thread, as a tool handler never
does — turns it into an ordinary attachment. `image_generate` is the first user
of it; a chart, a screenshot or an export will be the next.

The generation itself is the OpenAI images shape (`/images/generations`), the
one OpenAI, OpenRouter and most compatible gateways answer; a provider without
it is told so by name. Local diffusion is not attempted: it does not fit beside
the resident voice models on 12 GB. Privacy mode and local-only both refuse it.

While it draws, Chat shows the owner-supplied `ImageGeneration` effect at the
image's size with the prompt underneath — a wait of several seconds that
produces nothing until it produces everything deserves better than a spinner.

`imagery.py`, `chat.py`, `ImageGeneration.tsx`. Tests: `test_imagery.py`,
`ImageGeneration.test.tsx`.

### M6. The compression itself

Now that the sizes are recorded, the cap is real: one result may put 12,000
characters in front of the model (`MARVI_TOOL_RESULT_CAP`, `0` to switch it
off), and what is cut stays readable through `tool_more`.

Two rules make it safe. Only *string* values are shortened, so keys, numbers,
lists and nesting survive and a widget reading `result["sources"][0]["url"]`
still finds it. And anything Marvi's own code parses rather than reads — the
browser and computer drivers, confirmations, the widget tool, sub-agent control
— is never trimmed at all. The budget is shared across a result's fields, so a
dict of ten long strings is not ten times the cap.

`trimming.py`, `tools.py`. Tests: `test_trimming.py`.

### M10. Replayable runs

Every turn now carries one trace id, and each thing it does — what was asked,
each tool with its arguments and result, the answer and its tokens — is
appended to the observation journal under it. `GET /runs` lists recent turns,
`GET /runs/{trace}` reads one in order.

**Replay is a dry run, and that is the design.** `POST /runs/{trace}/replay`
runs the recorded question against a model again and *answers* each tool from
the recording rather than calling it; a tool the model invents gets a note
saying there is nothing to answer it with. Nothing reaches the world, nothing is
stored in the conversation, and the result says so in a field. What comes back
is a comparison — what it did then, what this model does now, and whether the
tools match — which is the question worth asking when a reply was strange.

`runs.py`, `chat.py`, `app.py`. Tests: `test_runs.py`.

### M11. Focus Assist, timidly

There is still no supported API, so this reads WNF — kernel state with no
header and no promise — through `NtQueryWnfStateData`. On this machine the
state name resolves and publishes *zero bytes*, which is what a machine that
has never switched Focus Assist on looks like and is indistinguishable from a
Windows build that moved it.

So the reading is deliberately timid: a four-byte 1 or 2 counts as Focus being
on and joins the existing busy rule; everything else — no data, another size, an
unknown value, an error, a future Windows — is "unknown" and changes nothing.
`MARVI_READ_FOCUS_ASSIST=0` switches it off.

**Unconfirmed on this machine.** Verifying it needs Focus Assist switched on
once in Windows Settings and the reading checked; that is the owner's setting to
change, not Marvi's. Until then the code is correct-by-construction and untested
against a live profile.

`focus.py`. Tests: `test_windows_busy.py`.
