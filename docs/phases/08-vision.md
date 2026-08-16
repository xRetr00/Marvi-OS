# Phase 8 — Vision

**Status:** planned
**Depends on:** Phase 3 media path, Phase 6 proactivity policy

Split out of Phase 6 so the proactive mind could ship without waiting on camera
work. Phase 6 is now cognition only; everything involving a camera lives here.

## Scope

- Always-on local presence and gesture inference with bounded resource use.
- Raw camera frames remain local; selected frames publish only for an explicit
  active vision task.
- Vision context tasks that do not bloat the foreground agent.

## Acceptance evidence required

- Camera privacy boundary test: raw frames never leave the machine, and frames
  publish only for an explicit active task.
- Idle GPU/RAM measurement with the voice stack resident, keeping the 2 GB
  headroom required by `AGENTS.md`.
- Gesture and presence accuracy sample on real hardware.
- Proof that a vision event reaching the mind still obeys the Phase 6 policy:
  it is journalled, capped by its surface ceiling, and never focuses a window.

## Notes

The smart-room sidecar already performs its own vision inference and emits
`vision_identity_state`, `vision_gesture`, and `vision_sleep_state` events. Those
were measured as the dominant event volume — 446 of a 500-event sample — and are
deliberately filtered out of the notable set today. This phase should decide
whether Marvi grows its own camera pipeline at all, or whether it consumes the
sidecar's and simply promotes selected vision events into the journal.
