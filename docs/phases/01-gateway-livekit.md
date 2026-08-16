# Phase 1 — Marvi Gateway and Local LiveKit

**Status:** scaffolded
**Depends on:** Phase 0 dependency pins

## Delivered

- Minimal Marvi Gateway Python package and health-contract test.
- LiveKit Agents dependency/configuration scaffold.
- Authority boundary documented: Gateway supervises; LiveKit owns RTC/session
  orchestration; voice adapters own inference.

## Remaining

- Start from the current official LiveKit Python agent starter.
- Pin and supervise the native Windows LiveKit Server binary on loopback.
- Add authenticated health, lifecycle, status/event, and confirmation-token
  contracts.
- Prove crash recovery and real local-room connection across process boundaries.

## Acceptance evidence

- Unit scaffold tests: present.
- Real server/worker recovery test: pending.
- Commits: `24ca7af` (initial scaffold).
