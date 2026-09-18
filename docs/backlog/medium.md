# Backlog — medium

Extensions of subsystems Marvi already has. Seven of the eleven were built on
2026-09-16; the four that were not say what they are waiting for.

| # | Item | State |
|---:|---|---|
| M1 | Long-chat compaction | done |
| M2 | Hooks that can refuse, and more of them | done |
| M3 | OpenAI-compatible API and ACP agent | not started — see below |
| M4 | MCP write access with provenance | done |
| M5 | Image generation | blocked on a contract — see below |
| M6 | Tool-output compression | measured; compression not built |
| M7 | Privacy mode, the whole of it | done |
| M8 | Chat search in the control center | done |
| M9 | Credential pools | done |
| M10 | Replayable runs | not started — see below |
| M11 | Focus Assist awareness | not started — see below |

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

`pre_tool_call` may return `{"action": "block", "message": …}` and the call is refused with that reason, recorded like any other
failure. A granted hook that *crashes* refuses too — a guardrail that failed
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

## Not done, and what each is waiting for

### M3. OpenAI-compatible API and ACP agent

Two features in one entry, and they are different sizes. The
`/v1/chat/completions` endpoint is a day: map the request onto a Chat thread,
stream the existing SSE path, guard it with `localauth`. Marvi *as* an ACP
agent is not — it means implementing the agent half of the protocol
(session/update/permission), deciding what a permission request looks like when
the client is an IDE rather than the Island, and qualifying it against at least
one real editor. Split them before starting; the endpoint alone is worth doing.

### M5. Image generation

Blocked on a contract, not on an API. Generating the image is one provider call;
the problem is that a generated image has nowhere to go. Chat renders images
from *attachment rows*, and a tool cannot create one because tool handlers do
not know which thread they are running in. The honest fix is a small contract —
a tool result that declares "this is a file for the current thread", which the
chat dispatcher turns into an attachment — and that contract is worth having
anyway (a chart, a screenshot, an exported file all want it). Do that first,
then image generation is genuinely small.

### M10. Replayable runs

Needs a trace id threaded through `ProviderClient` and the tool router, a
journal of calls per turn, and a drawer that replays one without executing any
tool that has side effects. The last part is the real work: "replay" that can
send an email is not a debugging tool, so it needs a dry-run mode the tool
router understands. A phase, not a milestone.

### M11. Focus Assist awareness

Still no supported API. The undocumented WNF state is readable through
`NtQueryWnfStateData`, and reading undocumented kernel state on a machine that
updates itself monthly is a thing to do deliberately, behind a flag, with a
fallback of "unknown" — not as the last item of a long day. The fullscreen and
presentation states that *are* documented already ship (see small #6).
