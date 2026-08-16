# Phase 5 — World Context and Memory

**Status:** planned
**Depends on:** Phase 4 policy/audit path

## Scope

- Official Composio SDK for supported account OAuth and tools.
- Email, LinkedIn, X, and other connected context retrieved on demand.
- External writes pass through Confirm/YOLO and idempotent audit boundaries.
- Select a maintained memory foundation after a focused bakeoff; add episodic,
  semantic, forget, and export flows.

## Acceptance evidence required

- External content remains untrusted data and never becomes system instruction.
- Sandbox read/write, revoked OAuth, reconnect, duplicate-write, and memory
  deletion/export tests.
