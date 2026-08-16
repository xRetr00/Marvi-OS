# Phase 3 — Full-Duplex Voice Loop

**Status:** planned
**Depends on:** Phases 0 and 1

## Scope

- Local wake word arms an official LiveKit `AgentSession` path.
- Native stateful streaming STT, streamed OpenCode Go response, and genuinely
  incremental local TTS.
- Continuous capture through playout, WebRTC AEC/noise suppression, local turn
  detection, interruption, and automatic rearm.
- Island reflects authoritative session state without owning audio logic.

## Acceptance evidence required

- Wake → listen → think → speak → barge-in → rearm on real hardware.
- Speaker double-talk without self-transcription.
- Latency telemetry and 60-minute soak with stable VRAM/session counts.
