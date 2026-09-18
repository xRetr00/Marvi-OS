# Phase 17 — Jobs board

Status: built, 2026-09-18. Depends on [Phase 16](16-sub-agents.md).

## Goal

Every sub-agent job, delegated coder run and user-created task becomes a durable
card on one board in the control center. Jobs survive a restart, carry their
history, and can be commented on, unblocked or cancelled by the owner.

## Source

Design: SQLite rows as the source of truth, append-only runs, comments and
events, and a dispatcher inside the gateway. Recorded in `UPSTREAM.md` when
built. OpenHuman's board (GPL-3.0) is a design reference only.

## Storage

One SQLite file beside the Gateway's other stores:

- `tasks` — id, title, body, assignee (`harvi`, `jarvi`, `talos`, `worker`, an
  ACP coder, or `owner`), mode, status, created_by (`marvi`, `owner`),
  created_at, updated_at.
- `task_runs` — one row per attempt: started/finished, exit_reason, summary,
  tokens, provider.
- `task_comments` — append-only; an owner comment on a running card is a
  `delegate_steer`.
- `task_events` — append-only transitions, for audit and the live stream.

This replaces the in-memory registries in `subagents.py` and `delegate.py`.

Built as `jobs.py`, at `jobs.sqlite3` beside the other stores. Every change
bumps a revision the long poll waits on.

## States

`todo` → `running` → (`awaiting_approval` | `blocked`) → `done` | `failed` |
`cancelled`.

`blocked` carries a reason (`needs_input`, `dependency`, `stalled`). On startup,
cards left `running` by a dead process become `failed` with
`exit_reason=restart`; their work on disk is untouched.

## Surfaces

- **Control center:** a Jobs page with one column per state, a card drawer with
  runs, comments and the spoken summary. Monochrome per `UI.md`.
- **Gateway:** `GET /jobs`, `GET/PATCH /jobs/{id}`, `POST /jobs/{id}/comments`,
  and a long-poll `?after=<revision>` stream like `/computer`.
- **Marvi:** `delegate` creates a card; `delegated_status` reads cards. Built
  as `Runner._card()` in `subagents.py`: a sub-agent job opens a card when it
  starts and closes it through `finish_run` when it ends, so a delegated job is
  on the board without anything having to remember to put it there.
- **Telegram:** finished and blocked cards follow the existing delivery rules.

Built: `jobs_board`, `job_add` and `job_update` tools; `GET /jobs` (with
`?after=`), `GET/PATCH/DELETE /jobs/{id}`, `POST /jobs` and
`POST /jobs/{id}/comments`; and the board itself on the Workflows page, beside
the automation rules that create work rather than in a page of its own.

## Not planned

Auto-decomposition into child cards, multiple boards, tenants, PR completion
contracts, drag-and-drop reassignment. Add each when a real workflow asks for it.

## Acceptance

Cards survive a Gateway restart; a running card interrupted by restart is shown
as failed with its reason; an owner comment reaches a running sub-agent; and
the board updates live without polling the renderer on an idle timer.

**Met, 2026-09-18**, by `test_jobs.py`:

| Gate | Where |
|---|---|
| Cards survive a restart | `test_a_restart_corrects_a_card_that_says_it_is_running` — a second `JobsStore` over the same file recovers one card. |
| A restarted card says so | Same test: `failed` with `exit_reason=restart`, and an event that says "restarted" in words. |
| An owner comment reaches a running sub-agent | `test_an_owner_comment_on_a_live_card_is_a_steer` — collected once by `unsent_steers`, never resent. |
| Live without an idle timer | `test_the_long_poll_waits_for_a_change_and_then_answers`; the window's `follow()` loop in `jobs-board.tsx` has no timer except the 3-second back-off for a Gateway that is not answering. |

**Not yet met.** Telegram delivery for finished and blocked cards: the card
states exist and the delivery rules exist, but nothing joins them.
