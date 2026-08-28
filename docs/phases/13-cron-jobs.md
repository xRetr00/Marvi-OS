# Phase 13 — Cron Jobs

Status: complete

## Outcome

Marvi OS has a reusable cron-job contract without adopting another product's
CLI, profile manager, gateway process, or messaging implementations.
Marvi Gateway remains the sole owner of durable jobs, execution, provider
routing, tool policy, audit, and the future messaging connection.

## Implemented

- Durable SQLite jobs supporting `30m` one-shots, `every 2h` intervals, ISO
  timestamps, local `HH:MM`, and five-field cron expressions.
- Fixed reminder/ARC actions plus isolated agent jobs with a self-contained
  prompt, per-job provider, model, reasoning effort, and exact tool allowlist.
- Agent rounds use ProviderClient and the existing ToolRegistry dispatch. They
  do not create Chat transcript entries and cannot bypass Confirm/YOLO.
- A single conditionally sensitive `cronjob` model tool implements create,
  list, get, runs, update, pause, resume, run, and remove. The original
  `schedule_*` tools remain compatibility aliases.
- Durable execution rows record source, state, route, model, tokens, tools,
  bounded output/error, and delivery outcome. Repeat counts disable completed
  jobs automatically.
- Delivery is a typed Gateway adapter seam. The default advertises only
  `local`, retaining output without claiming a messaging send. Future adapters
  can expose destinations and deliver results without changing cron execution.
- The desktop Schedules page exposes agent/fixed mode, model controls, tool
  selection, delivery selection, route details, latest output/error, run-now,
  pause/resume, and removal.

## Upstream boundary

The precise source, pinned revision, license, modification boundary, and update
method are recorded only in `docs/UPSTREAM.md`.

## Acceptance evidence

- 23 focused schedule tests pass, including legacy reminders, schedule parsing,
  restart durability, model/tool allowlisting, run history, messaging failure,
  and conditional tool confirmation.
- All 934 Gateway tests pass with the expanded response models and scheduler
  wiring (one expected Windows Hugging Face symlink-cache warning).
- All 252 desktop tests pass; both TypeScript targets and the production
  Electron/Vite build pass.
- Gateway Ruff, desktop ESLint (zero errors; repository line-ending warnings
  remain), and `git diff --check` pass.
