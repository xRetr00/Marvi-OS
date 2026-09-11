# Phase 16 — Sub-agents: Harvi, Jarvi and Talos

Status: 16A–16D implemented with automated, real-host and voice-pipeline
evidence, 2026-09-11 (16D: Codex verified over ACP; Claude Code blocked on the
host's revoked login). Not yet exercised: microphone and
speaker audio in the loop, and Talos on the real host.
Design approved by the owner in conversation. Plan:
[`docs/plans/PHASE-16-SUB-AGENTS.md`](../plans/PHASE-16-SUB-AGENTS.md).

## Evidence — 2026-09-11

Host: Ryzen 5 3600X, 16 GB, RTX 3060 12 GB, Windows 11. Provider: OpenRouter
`inclusionai/ling-3.0-flash` (the configured `main` role). Cua 0.24.0.
`scripts/qualify-subagents.py` builds the full Gateway and delegates over
`POST /tools/delegate`, settling the fix-mode confirmation through
`/confirmations/{token}` as the Island does.

| Job | `delegate` answered | Job ran | Tokens | Outcome | Independent check |
|---|---:|---:|---:|---|---|
| Harvi, fix, failing `add` fixture | 2,625 ms¹ | 8.0 s | 14,740 | completed: found `a - b`, changed to `a + b`, ran pytest | fixture pytest: `1 passed` |
| Jarvi, open Notepad, read title, close | **30.7 ms** | 44.3 s | 43,748 | completed: "Untitled - Notepad", closed via Exit | `tasklist`: Notepad not running |

¹ The first request of the process, including the confirmation round trip and
first-call warm-up; the Jarvi row is the steady-state cost a voice turn pays.

Automated: 1,835 Gateway tests (full suite), including 29 sub-agent tests (loop
contract, blocked tools, stall and in-tool patience, breaker, stop/steer, caps,
confirmation park/approve/deny/expire, fix grant, read-before-edit, and two
real-app tests through `/confirmations` and `delegate_approve`) and 12
coding-tool tests; 350 agent tests (voice catalogue excludes the multi-step
tools; approval requests pushed once per token; a delegation approved by voice
is followed); 508 desktop tests and typecheck (Island names the actor).

### Voice pipeline to Jarvi

`evals/voice_delegation.py` drives the production voice agent — the real
`MarviVoiceAgent`, persona, context blocks, Gateway tool catalogue,
`on_end_of_turn` path and `delegated.py` watcher — with text where the
recogniser's transcript would be, against this checkout's Gateway and the real
Cua worker. Evidence: [`voice-delegation-2026-09-11.json`](../evidence/voice-delegation-2026-09-11.json),
same host and model as above, on the uncommitted working tree over `6d5df8fe`.

| Heard | Said | Tools |
|---|---|---|
| Can you open Notepad, tell me the title of its window, and then close it? | "One sec." | `delegate(agent=jarvi, …)` (recorded in the next window) |
| While that's going, what's seven times eight? | "56. Jarvi is opening Notepad and will report the window title shortly." | — |
| Okay, thanks. | "The title was *F4 - Notepad, and Jarvi closed it." | — |

Jarvi ran 25.7 s in parallel with the second turn and completed; the third
turn carried its report without being asked. Voice's catalogue had no
`computer_action`.

Two earlier runs failed and changed the design, not only the harness:

1. Cold in-process Gateway: the embedding import (21 s) and `/context` (12 s)
   timed out the first tool call. The eval now warms the Gateway first, as a
   real Gateway is warm long before a conversation.
2. Warm, but the voice model reached for `terminal_run notepad.exe` and misused
   `computer_control` instead of delegating. The voice prompt now says that
   multi-step work goes to a sub-agent with `delegate` and that
   `computer_control` is only Stop / Private input / Resume; the
   `computer-use` and `browser-use` skill descriptions stopped telling her to
   operate apps directly. `test_the_voice_prompt_kept_every_rule` pins it.

Also observed: the voice model still speaks a filler ("One sec.") before the
call, and once computed `7*8` with `terminal_run`; both are the voice model's
existing habits, not part of this phase.

Outstanding: microphone and speaker audio in the same loop, with the Island
visible; Talos against the embedded browser on the real host.

## 16D — Outside coders over ACP — 2026-09-11

`delegate_to_coder` now runs Claude Code, Codex, OpenCode or Gemini CLI as a
sub-agent job over the Agent Client Protocol (`acp_coders.py`, SDK
`agent-client-protocol==0.12.1`). The job is an ordinary `subagents.Job`: it
shows in the desktop feed with its avatar and live transcript, reports to voice
through `delegated.py`, stops with Stop (ACP `session/cancel`), and falls under
the stall watcher. Session updates map to the transcript (messages, tool calls
with ok/failed) and the plan to the todo list.

- **Mode.** Investigate asks the agent for its read-only mode (`plan`,
  `read-only`); fix for its edit mode (`acceptEdits`, `auto`).
- **Permission.** Reads, searches and thinking are allowed. Edits are refused
  in investigate and allowed under an approved fix job, as are commands;
  anything else becomes a Marvi confirmation through the internal
  `coder_permission` tool, so the Island, a spoken yes (`delegate_approve`) or
  Telegram answers it and YOLO allows it. `ToolSpec.internal` keeps that tool
  out of every listing -- no model is offered it.
- **Fallback.** A coder with no ACP server here still runs through the old
  one-shot CLI path in `delegate.py`.
- **Windows.** Commands resolve to a runnable `.exe`/`.cmd`: `shutil.which("npx")`
  returned npm's extensionless sh script and the first real run failed with
  WinError 193 for both adapters.

Evidence: 14 tests against the real SDK and a fake ACP agent subprocess
(`tests/fixtures/fake_acp_agent.py`): report and transcript, chosen modes, fix
grant, investigate refusal, owner confirmation park/deny, YOLO, cancel,
refusal, start failure, roster, `delegate_to_coder` routing, internal tool
hidden, Windows resolution. Real run (`scripts/qualify-subagents.py --acp`,
Codex CLI 0.132.0 through `@agentclientprotocol/codex-acp@1.11.0`): fix job on
the failing fixture completed in 36.5 s with a live transcript
(execute → edit → execute pytest, all ok); independent pytest `1 passed`;
`delegate_to_coder` answered in 283 ms. Claude Code 2.1.232 through
`@agentclientprotocol/claude-agent-acp@0.76.0` reached a session and failed
with `401 OAuth access token has been revoked` -- the host's Claude login, not
the protocol; the job now says it needs signing in again. OpenCode and Gemini
CLI are not installed here.

## Sub-agent UI — 2026-09-11

- **Gateway feed.** Each job keeps its last 60 transcript events (its own
  words, each step as `tool key=value` with long values reduced to their
  length, ok/failed, approvals, the ending — never a tool's result) and its
  todo list. `GET /agents?after=<revision>` (roster + recent 20 jobs) waits on
  a revision like `/computer`; `GET /agents/jobs/{id}` adds the transcript;
  `POST /agents/jobs/{id}/stop` is `delegate_stop`. All three behind
  `localauth.guard`.
- **Desktop.** One nanostores atom long-polls the feed while anything is
  subscribed. Status bar agents item and popover; Chat's `delegate` card
  (outside the folded work log); the Voice activity card's strip. Avatars per
  the owner's design — the UI contract's single colour exception.
- **Evidence.** 38 sub-agent Gateway tests (5 new: transcript content and
  bounds, revision wait, unknown job, endpoint auth); 16 renderer tests (state
  table, card states, transcript, roster, receipt parsing, work-log exclusion);
  desktop suite and typecheck green. Visual check in a throwaway Vite probe
  against a mocked feed: roster with expanded description, working/recent
  lists, and handing-over, approval, stalled, lost and expanded-transcript
  cards; no console errors. Not yet seen inside the running Electron shell.

## Refinements made while building

- **Stop does not pause the computer.** A stopped job sends nothing further —
  the rest of its round's calls are refused — and an action already in flight
  finishes under its own lease. Issuing `computer_control stop` would leave the
  computer paused and the next request stuck until someone resumed it; the
  Island's Stop remains the way to pause.
- **One confirmation for a Harvi fix job.** In Confirm mode, per-call
  confirmation of every `file_edit` made fix mode unusable. `delegate` is
  sensitive when `mode=fix`; that approval covers the job's `file_write`,
  `file_edit`, `file_delete` and `terminal_run` (`subagents.GRANTED`), exactly
  as approving `codex --sandbox workspace-write` did. Validation, the workspace
  policy and audit still apply; everything else is confirmed per action.
- **Read-before-edit** is enforced in the runner for existing files; a new file
  needs no read.

## Goal

Marvi hands multi-step work to sub-agents and keeps talking. Three built-in
sub-agents ship with her under static names; anything else complex goes to a
generic sub-agent with a generated name. The user never talks to a sub-agent:
they tell Marvi, and Marvi tells the sub-agent.

| Name | Job | Tools |
|---|---|---|
| **Harvi** | Marvi's native coder | every Marvi tool plus the coding tools below |
| **Jarvi** | computer use (Windows applications) | `computer_*` (screenshots read by the Vision provider) |
| **Talos** | browser use (anything with a URL) | `browser_*`, `web_*` |

Built-ins are ordinary sub-agents with a stronger harness and a fixed name —
same runtime, same contract, same tests. Web search stays a direct tool; it is
one fast call and does not need an agent.

## Why

**Computer use blocks the voice turn.** The voice model runs the Cua
look → act → check loop itself ([computer-use skill](../../skills/computer-use/SKILL.md)).
Phase 15 fixture timings are launch ≈4.5 s, observation ≈1.7 s, click ≈1.3 s,
so a ten-step task holds one spoken turn for 20–40 s. The owner confirmed the
symptom is exactly that: long silence, and Marvi cannot be talked to until it
ends. Browser tasks have the same shape.

**The coding harness never got its agent.** [`delegate.py`](../../services/gateway/src/marvi_gateway/delegate.py)
shells out to `claude -p` / `codex exec`, and [`coding-agent.md`](../../prompts/coding-agent.md)
was written to become "Marvi's own coding sub-agent" system prompt. That agent
is Harvi.

The push-back seam already exists: [`delegated.py`](../../services/agent/src/marvi_agent/delegated.py)
puts a finished job in front of the voice model on the next turn without ever
blocking one.

## Research (2026-09-11)

| Source | License | Taken |
|---|---|---|
| [Hermes Agent delegation](https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation) | MIT | The contract: fresh child context, inherited tools minus a blocked set, summary-only return, `completed/failed/interrupted` with an exit reason, stop and steer, progress-based stall detection. Design only; Hermes's `AIAgent` is not vendored. |
| [Hermes Kanban](https://github.com/nousresearch/hermes-agent/blob/main/website/docs/user-guide/features/kanban.md) | MIT | Schema and states for [Phase 17](17-kanban.md). |
| [OpenHuman agent harness](https://tinyhumans.gitbook.io/openhuman/developing/architecture/agent-harness.md) | **GPL-3.0** | Ideas only, no code: `AwaitingUser`/`Incomplete` result states, circuit breaker after three identical tool failures, per-agent tool scopes. |
| [OpenClaw sub-agents](https://docs.openclaw.ai/tools/subagents) | MIT | Always non-blocking spawn with an announce on completion — already Marvi's `delegated.py` shape. |
| [Agent Client Protocol](https://agentclientprotocol.com/get-started/agents) | Apache-2.0 SDK | Later milestone 16D: one client for Claude Code, Codex, OpenCode, Gemini CLI. |
| [Piebald-AI/claude-code-system-prompts](https://github.com/Piebald-AI/claude-code-system-prompts) `e46a5fc1` (Claude Code v2.1.268) | repo MIT; prompt text is Anthropic's | Harvi's harness is **adapted**: rules and behaviours rewritten in Marvi's voice, no verbatim text. The repository's MIT grant cannot cover text extracted from proprietary Claude Code. |

Not adopted: generic multi-agent frameworks (OpenAI Agents SDK, LangGraph) — a
second orchestrator beside LiveKit and the Gateway's single tool policy;
Vibe Kanban — vendor shut down April 2026; Cua Agent SDK's own loop — bypasses
per-action confirmation and would void Phase 15 qualification.

## Architecture

### Definitions

`prompts/<name>.md`, the existing prompt-registry format; a `when-to-use`
line is what already makes a prompt an agent (`prompts.agents()`):

```
<!--
name: "Agent: Harvi"
description: "Marvi's coder ..."
when-to-use: "..."
tools:            # allowlist; "*" means every tool
  - "file_read"
denied-tools:     # removed after the allowlist
  - "speak"
model: "main"     # provider job role; optional, default main
max-rounds: 60
-->
```

The body is the system prompt. `prompts/harvi.md`, `jarvi.md`, `talos.md`
and `worker.md` ship in the repository. `worker` is the generic sub-agent: `tools: "*"`
minus the blocked set, and a generated display name from a short pool listed
in its frontmatter, falling back to `worker-<id>`.

### Loop

New `services/gateway/src/marvi_gateway/subagents.py`, reusing what Chat
already has rather than Chat itself (Chat is bound to its thread store and an
8-round cap):

- `ProviderClient.call_with_fallback` for the model call, with the definition's
  provider role;
- `tool_call_prose.recover` for calls a model typed out instead of making;
- the Gateway tool dispatch, so policy, confirmation tokens and audit apply
  unchanged;
- `schemas_from_registry`, filtered by the definition.

Its own message list per job. The last round is offered no tools, as in Chat,
so a job that runs out of rounds still reports what it found.

### Contract

- **Fresh context.** The job receives only its task text, the definition's
  prompt, and the workspace `AGENTS.md` for Harvi. It cannot see the
  conversation — Marvi writes the task for someone who was not there, as the
  existing delegation skill already teaches.
- **Blocked for every sub-agent** (`subagents.BLOCKED`): every `delegate*`
  tool and `delegate_to_coder`, `memory_remember`, `memory_forget`,
  `note_about_user`, `telegram_send`, `send_email`, `speak`,
  `end_conversation`, `cronjob`, `schedule_add`, `clarify`, `ask_secret`.
  Marvi owns memory, messages, schedules and questions to the owner;
  sub-agents report and she acts. No nesting in this phase.
- **States:** `running`, `awaiting_approval`, `completed`, `failed`,
  `interrupted`, plus `exit_reason` (`completed`, `max_rounds`, `stopped`,
  `stalled`, `error`).
- **Summary only.** Intermediate tool calls stay in the job. Marvi receives the
  final report, written to be spoken.
- **Circuit breaker:** three identical failing tool calls end the job as
  `failed` with the repeated error.
- **Stall:** no model call or tool result for 450 s ends the job `stalled`;
  inside a single tool call the limit is 1,200 s, since a foreground test run
  may take `terminal_run`'s full ten minutes.
- **Concurrency:** three jobs at once (the existing `MAX_RUNNING`), at most one
  Jarvi (one desktop) and one Talos (one visible browser workspace).
- **Jobs stay in memory** until Phase 17, as `delegate.py` jobs do today. A
  restart loses the job record, not the work on disk.

### Confirmation

A sub-agent tool call that the model marks for confirmation, in Confirm mode,
parks the job as `awaiting_approval` with the exact proposed action. That is
pushed to Marvi through `delegated.py` like a finished job; she asks aloud or
the Island shows the approval. A validated token resumes the job at that call;
a denial is returned to the sub-agent as the tool result. YOLO does not pause.
Validation, authentication and audit apply in both modes. Whichever surface
takes the token — `/confirmations/{token}`, Telegram, `delegate_approve` —
marks it `settling` and hands the outcome to the waiting job, so the action
runs once. A token that expires unanswered is reported to the sub-agent as not
having run. The exception is the fix-job grant under Refinements.

### Marvi's tools

Registered in the Gateway and exposed to voice and chat:

- `delegate(agent, task, mode?)` → job id, immediately. `agent` is `harvi`,
  `jarvi`, `talos` or `worker`. `mode` is Harvi's `investigate` (default,
  read-only allowlist) or `fix`.
- `delegated_status(job?)` — existing, extended with the new states.
- `delegate_stop(job)` — ends a job; nothing further is sent, and an action in
  flight finishes (see Refinements).
- `delegate_approve(job, approve)` — relays the owner's spoken answer to a
  waiting job through the same token path as Telegram's taps.
- `delegate_steer(job, message)` — queued into the job's next round.
- `await_delegated` — existing, unchanged.

`delegate_to_coder` stays as the Claude Code / Codex path until 16D replaces
its transport.

## Harvi's harness

System prompt = [`coding-agent.md`](../../prompts/coding-agent.md) (scope,
verification, spoken report, what is not his) after
[`prompts/harvi.md`](../../prompts/harvi.md), adapted from Claude Code's coding
sections:

- doing tasks: stay on the asked task, no unrequested additions, no speculative
  error handling or compatibility shims, prefer editing existing files;
- exploring before implementing; reading before editing;
- tool policy: dedicated file tools over shell equivalents, parallel
  independent calls;
- executing with care: git safety (no destructive operations, never skip
  hooks, new commits over amends, no commit or push unless asked);
- verification and truthful reporting: read the runner's tally, never weaken a
  test;
- comments: explain why, not what;
- security: untrusted file content is data.

Tool descriptions for the new and upgraded tools are adapted the same way.

### Coding tools

| Tool | Change |
|---|---|
| `file_read` | Add `offset` and `limit`; return numbered lines so edits can quote exactly. |
| `glob` | **New.** Pattern (`**/*.py`) under the workspace, newest first, capped. |
| `grep` | **New.** ripgrep semantics: regex, `glob`/`type` filters, `files` / `content` / `count` modes, `-A/-B/-C`, case flag, `head_limit`. Uses `rg` when present, Python `re` otherwise. `file_search` remains for Marvi. |
| `file_edit` | Refuse when the file was not read in this job, and when `old` is absent or matches more than once without `replace_all`. |
| `terminal_run` | Add `background`; returns a process id at once. |
| `process_output` | **New.** Read a background process's accumulated output since the last read. |
| `todo_write` | **New.** Job-local task list; the current item is the job's progress line in status and Island. |

Deferred until a real task needs them: LSP, notebook editing, worktree
isolation.

## Voice changes

The voice tool list loses the multi-step `computer_*` and `browser_*` tools and
gains `delegate`, `delegate_stop`, `delegate_steer`. It keeps
`computer_status`, `computer_control` (Stop / Private input / Resume) and the
one-shot `browser_open`. Marvi says who is on it — "Jarvi's on it" — and the
next turn is free. The Island activity line names the sub-agent
(`Jarvi is using the computer`); controls and confirmation priority are
unchanged. The `computer-use` and `browser-use` skills move to the sub-agents'
prompts; Marvi gets a short delegation note instead.

## Milestones

| Milestone | Outcome | Acceptance |
|---|---|---|
| **16A — Runtime + Jarvi + Talos** | `subagents.py`, definitions, `delegate*` tools, voice list change, Island label | Voice→Jarvi handoff returns within one turn and the next spoken turn is answered while Jarvi runs, on the Phase 15 Windows fixture. Stop drains native work. Confirm-mode pause/resume and YOLO both proven. |
| **16B — Harvi** | Harness prompt, new and upgraded coding tools | A fixture repository with a failing test: `investigate` changes no file; `fix` edits, runs the suite, and reports the runner's tally. Read-before-edit and unique-match refusals tested. |
| **16C — Worker** | Generic sub-agent with generated names | A multi-step non-coding task completes and reports; blocked tools are absent from its schema. |
| **16D — External coders over ACP** | `delegate_to_coder` transport becomes an ACP client (Claude Code, Codex, OpenCode, Gemini CLI) with streamed progress, cancel, and permission requests routed to Marvi's confirmation | Separate evidence; not a condition of 16A–C. |

Each milestone is its own commit with tests, phase evidence, README and
implementation-log updates.

## Tests

Per AGENTS.md, for each built-in: basic flow, intended tool call, error
behaviour, and the workflow transition (voice → sub-agent → pushed result).
Plus: stall, circuit breaker, stop, steer, concurrency caps, blocked tools,
`max_rounds` final tool-free round, confirmation pause/resume/deny, and
schema filtering. Jarvi and Talos acceptance uses the real Cua worker and
browser workspace, not mocks.

## Documents to change with 16A

- `DECISIONS.md` — ADR-028: sub-agents are Gateway-owned specialists on the
  single tool policy. It supersedes ADR-020: that decision rejected re-coupling
  the ambient runtime to Marvi Agent's core; sub-agents share Marvi's policy
  and add no second core.
- `UPSTREAM.md` — Hermes Agent (design), OpenHuman (design, GPL, no code),
  Piebald prompt collection (adapted text, commit pin).
- `ARCHITECTURE.md`, `UI.md` (Island label), `README.md`,
  `skills/delegating-to-a-coding-agent`, `skills/marvi-agent`,
  `docs/phases/README.md`.

## Out of scope

Durable jobs and a board ([Phase 17](17-kanban.md)); nested sub-agents; a
per-agent model picker in Settings (the `model` role in the definition covers
it); new built-ins beyond the three.
