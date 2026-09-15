# Backlog

Features Marvi does not have yet, found by comparing Marvi OS with Hermes Agent,
OpenClaw and OpenHuman on 2026-09-16, each with a plan. It is not a promise and
not a phase: an item becomes work when it gets a `docs/phases/NN-*.md` file with
acceptance gates, the way the Jobs board became [Phase 17](../phases/17-kanban.md).

Messaging channels (Discord, Slack, Signal, WhatsApp, email) are already
researched in [MESSAGING-CHANNELS.md](../research/MESSAGING-CHANNELS.md) and are
not repeated here.

| Tier | File | What it holds |
|---|---|---|
| Big | [big.md](big.md) | new subsystems: a phase each |
| Medium | [medium.md](medium.md) | extensions of what exists: a milestone each |
| Small | [small.md](small.md) | a day or less each |

## Shipped from this backlog — 2026-09-16

Ten items small enough for one change. Each has tests; the evidence column is
what was checked beyond them.

| # | Feature | Where | Tests | Beyond the tests |
|---:|---|---|---|---|
| 1 | File checkpoints: `file_write`/`file_edit`/`file_delete` keep a copy first; `file_checkpoints` and `file_restore` tools | `checkpoints.py`, `workspace.py` | `test_checkpoints.py` | — |
| 2 | Clipboard tools: `clipboard_read` (enveloped as untrusted), `clipboard_write` | `desk.py` | `test_desk.py` | real Win32 read on the dev host; write not run there because the clipboard held non-text data |
| 3 | Media keys: `media_control` (play/pause, next, previous, stop, volume, mute) | `desk.py` | `test_desk.py` | not pressed on the dev host (would pause the owner's audio) |
| 4 | Plugin `pre_tool_call` / `post_tool_call` hooks (Hermes names; observers) | `tools.py`, `plugins.py` | `test_tool_hooks.py` | — |
| 5 | Local-only mode: `MARVI_LOCAL_ONLY=1` refuses every cloud model call, voice included | `providers/client.py` | `test_provider_client.py` | — |
| 6 | Presenting / fullscreen hold: proactive speech and the Island wait while Windows says not to interrupt | `focus.py`, `policy.py`, `pending.py` | `test_windows_busy.py` | real `SHQueryUserNotificationState` read on the dev host |
| 7 | Chat search: `GET /chat/search` and `chat_search` tool over every thread | `chat.py`, `app.py` | `test_chat_search.py` | — |
| 8 | `marvi mcp serve`: Cortex recall and chat search offered to Claude Code, Cursor, Codex over MCP stdio (read-only) | `mcp_serve.py`, `cli.py` | `test_mcp_serve.py` (real MCP session) | real stdio run; `memory_recall` answered by the live Gateway |
| 9 | `marvi memory export --obsidian DIR`: one note per subject, relations as `[[links]]` | `vault.py`, `cli.py` | `test_vault.py` | — |
| 10 | Summon hotkey (`Alt+Shift+M`, `MARVI_SUMMON_HOTKEY`) starting voice the way the wake word does | `apps/desktop/src/main/summon.ts`, `index.ts` | `summon.test.ts`, typecheck | not pressed in a running build |

Follow-ups each of these left are listed in the tier files, marked
*extends #n*.

## How an item is written

Every entry has the same parts, so it can be lifted into a phase file:

- **Why** — the gap, in one or two sentences, and who already has it.
- **Upstream** — what to reuse, per the upstream-first rule in `AGENTS.md`.
- **Plan** — ordered steps.
- **Done when** — acceptance, in the phase-file style.
- **Not planned** — the tempting extras that are out.
