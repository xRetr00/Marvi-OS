# Phase 0 — Foundations and Hardware Proof

**Status:** in progress
**Depends on:** none

## Delivered

- Independent repository, engineering rules, architecture, UI contract,
  upstream ledger, decision log, and native voice benchmark protocol.
- Target hardware/toolchain inventory for Windows and RTX 3060 12 GB.
- Explicit rejection of WSL2, Whisper-family overlapping-window STT, Qwen3-TTS,
  full Unmute deployment, and sentence-buffered pseudo-streaming TTS.

## Remaining

- Run native streaming STT/TTS candidates on the target machine.
- Measure first partial, finalization, first audio, realtime factor, interruption,
  VRAM/RAM, and a 60-minute soak.
- Select primary and fallback engines while preserving at least 2 GB VRAM
  headroom.
- Audit the real `D:\smart-room-plugin` bridge and Marvi updater boundary.

## Acceptance evidence

- Benchmark artifacts: pending.
- Selected model revisions: pending.
- Commits: `24ca7af` (repository foundation).
