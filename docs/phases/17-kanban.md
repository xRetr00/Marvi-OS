# Phase 17 — Jobs board

Status: planned, 2026-09-11. Depends on [Phase 16](16-sub-agents.md).
Plan only; nothing here is part of the Phase 16 build.

## Goal

Every sub-agent job, delegated coder run and user-created task becomes a durable
card on one board in the control center. Jobs survive a restart, carry their
history, and can be commented on, unblocked or cancelled by the owner.

## Source

Adapted from [Hermes Kanban](https://github.com/nousresearch/hermes-agent/blob/main/website/docs/user-guide/features/kanban.md)
(MIT): SQLite rows as the source of truth, append-only runs, comments and
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
- **Marvi:** `delegate` creates a card; `delegated_status` reads cards.
- **Telegram:** finished and blocked cards follow the existing delivery rules.

## Not planned

Auto-decomposition into child cards, multiple boards, tenants, PR completion
contracts, drag-and-drop reassignment. Add each when a real workflow asks for it.

## Acceptance

Cards survive a Gateway restart; a running card interrupted by restart is shown
as failed with its reason; an owner comment reaches a running sub-agent; and
the board updates live without polling the renderer on an idle timer.
