# Phase 3 — Full-Duplex Voice Loop

**Status:** in progress
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

## Implemented

- Pinned Nemotron 3.5 ONNX and VibeVoice Realtime payload manifests, downloads,
  checksums, voice presets, and setup diagnostics.
- Native Rust `parakeet-rs` sidecar plus a stateful LiveKit streaming STT adapter.
- Incremental VibeVoice PCM generation plus LiveKit sentence stream adapter.
- Official `AgentSession` with local VAD/turn detection, barge-in tuning, OpenCode
  Go streaming LLM, and a transcript-level `Marvi` wake gate.
- Local LiveKit Server start script and worker entrypoint.

## Still required before this phase can be marked complete

- Real speaker double-talk/barge-in test and unattended 60-minute soak.

## Hardware bakeoff evidence

[`../evidence/phase-3-hardware-bakeoff.json`](../evidence/phase-3-hardware-bakeoff.json)
records an RTX 3060 run. With three diffusion steps, VibeVoice produced its
first PCM chunk in 0.735 s at 0.994 RTF and 2.683 GiB peak allocated VRAM.
Nemotron transcribed the synthesized 5.333 s sample in 3.024 s (0.567 RTF),
correctly recovering “Marvi”; post-bakeoff GPU use was 4.245 GiB.

Kokoro ONNX was also measured as a fallback: 54 voices and 0.406 RTF, but it
did not yield its first chunk until the full utterance was synthesized (2.493
s for the benchmark sentence), so it does not replace VibeVoice's acoustic
streaming path.
