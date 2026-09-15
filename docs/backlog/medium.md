# Backlog — medium

Extensions of subsystems Marvi already has. One milestone each.

## M1. Long-chat compaction

**Why.** No compaction exists in `chat.py`: a long thread's history grows until
it no longer fits the model's context window. Hermes has `/compress`; Claude
Code compacts automatically.

**Upstream.** None needed: `ProviderClient` and an auxiliary model role.

**Plan.**
1. Before a turn, measure the history against the model's context window (the
   catalog value the context meter already reads).
2. Over a threshold (default 70%), summarise the oldest turns into one stored
   `background: compaction` row via a `compaction` auxiliary role; keep the
   last N turns verbatim, and the cacheable prefix untouched.
3. The context meter shows that compaction happened; the original rows stay in
   the database (and in `chat_search`).
4. `/compact` in the composer to do it on demand.

**Done when.** A 300-turn fixture thread answers a question about turn 5 after
compaction, and never exceeds the window.

**Not planned.** Compacting voice sessions (they are short by nature).

## M2. Hooks that can refuse, and more of them (*extends #4*)

**Why.** Shipped tool hooks observe only. Guardrails ("never let any tool touch
`D:\Finance`") need a veto, and plugins want turn and memory events too.

**Plan.**
1. `pre_tool_call` may return `{"action": "block", "message": ...}` (Hermes'
   shape). A block is a refusal the model sees, recorded in the audit log.
2. It cannot *unblock*: confirmation and the sleep guard still apply after it.
3. New events: `pre_turn`, `post_turn`, `on_memory_write`, `on_confirmation`.
4. A decision record in `DECISIONS.md`, because a veto hook is policy.

**Done when.** A fixture plugin blocks `file_delete` under one folder in both
Confirm and YOLO, and a hook that crashes still never breaks a call.

## M3. Marvi as an OpenAI-compatible API and an ACP agent (*extends #8*)

**Why.** `marvi mcp serve` gives other agents Marvi's memory. Hermes also
exposes an OpenAI-compatible endpoint (any chat frontend) and an ACP agent (IDE
chat panels).

**Upstream.** `agent-client-protocol` (already pinned, used as a client) has the
agent side; FastAPI for `/v1/chat/completions`.

**Plan.**
1. `POST /v1/chat/completions` on loopback, guarded by `localauth`, mapped onto
   a Chat thread per `user` field; streaming via the existing SSE path.
2. `marvi acp` — Marvi as an ACP agent over stdio for Zed/JetBrains, with tool
   permission requests routed to the Island.

**Done when.** Open WebUI and Zed both hold a conversation with Marvi, with
approvals appearing on the Island.

## M4. MCP write access with provenance (*extends #8*)

**Why.** `mcp serve` is read-only because a memory written by an outside agent
needs a source the Cortex model can weigh.

**Plan.** Add `memory_remember` over MCP, stored with `source = "mcp:<client
name>"` and `trusted = false`; the Cortex page shows and filters by source;
dreaming may promote it only after the user confirms.

**Done when.** A memory written from Claude Code is visible, marked untrusted,
and never reaches a prompt as instruction.

## M5. Image generation

**Why.** Hermes (FAL), OpenHuman (Seedream) generate images; Marvi cannot.

**Upstream.** Provider APIs already in the catalog (OpenAI `gpt-image-*`,
OpenRouter image models). Local diffusion does not fit beside resident voice
models on 12 GB and is not planned.

**Plan.** `image_generate(prompt, size)` through `ProviderClient` with an
`image` auxiliary role; output saved as a Chat attachment and rendered with the
existing image tile; refused in local-only mode with a clear reason.

**Done when.** Chat shows a generated image, usage is recorded per provider,
and local-only mode refuses it.

## M6. Tool-output compression

**Why.** Big tool results (web pages, logs, file reads) are pasted whole into
the context. OpenHuman reports up to 80% fewer tokens by compressing them; on
the voice path tokens are latency.

**Plan.**
1. Measure first: per-tool result size from `observations` over a week.
2. Per-tool budgets; over budget, keep head/tail and a structured summary from a
   cheap auxiliary role, with a `more` handle to fetch the rest.
3. Never compress confirmation payloads or anything the user asked to see
   verbatim.

**Done when.** Median voice-turn input tokens fall measurably on the recorded
baseline with no drop in the voice eval pass rate.

## M7. Privacy mode, the whole of it (*extends #5*)

**Why.** `MARVI_LOCAL_ONLY` covers model calls. Web search, Composio, Telegram,
hosted memory providers and update checks still reach the network.

**Plan.** One switch in the control center (and the status bar indicator,
like YOLO) that sets local-only models and disables each network feature with a
visible reason; `marvi doctor` reports what is still networked.

**Done when.** With privacy mode on, a packet capture of a scripted session
shows no traffic except loopback and LAN.

## M8. Chat search in the control center (*extends #7*)

**Why.** Search exists as an endpoint and a tool, not in the UI; LIKE scans
every message.

**Plan.** A search box above the thread list; results grouped by thread, click
to open at the message; add an FTS5 table with triggers (as `memory.py` has)
once a history exceeds ~50k messages.

**Done when.** Typing a word finds and opens the message in an archived thread.

## M9. Credential pools

**Why.** One key per provider means one rate limit. Hermes rotates several.

**Plan.** Allow `OPENROUTER_API_KEY_2..n`; on 429 cool down the key, not the
provider; usage recorded per key suffix.

**Done when.** A 429 on key 1 moves the next call to key 2 without a cooldown on
the provider.

## M10. Replayable runs

**Why.** OpenHuman replays a run with per-call cost. Marvi has usage totals and
logs, but cannot show "this turn: these calls, these tools, this cost".

**Plan.** A per-turn trace id through `ProviderClient` and the tool router
(observations already carries timings); an Activity drawer that shows the
trace and re-runs it against a chosen model in a dry-run mode.

**Done when.** A chat turn can be opened as a trace and replayed with a
different model without executing any tool with side effects.

## M11. Focus Assist (Do Not Disturb) awareness (*extends #6*)

**Why.** Shipped #6 reads presenting and fullscreen. Windows' Focus / Do Not
Disturb has no supported API; the undocumented WNF state
`WNF_SHEL_QUIETHOURS_ACTIVE_PROFILE_CHANGED` is what third-party tools read.

**Plan.** Spike reading it via `NtQueryWnfStateData` behind a feature flag with
a fallback of "unknown"; if it proves stable across two Windows builds, feed it
to the same `busy` rule.

**Done when.** Turning Focus on in Windows Settings holds a reminder on the
target host, and an unsupported build simply reports unknown.
