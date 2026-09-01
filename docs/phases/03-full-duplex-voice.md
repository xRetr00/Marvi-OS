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

- Pinned Parakeet TDT ONNX and Kokoro payload manifests, downloads, checksums,
  voices, and setup diagnostics.
- Chunked Parakeet ONNX Runtime STT adapter on CPU.
- Kokoro clause-streaming LiveKit adapter as the default, plus isolated
  selectable CuteTTS Distill and VoXtream2 PCM sidecars. These
  options remain experimental until their individual hardware gates pass.
- Official `AgentSession` with local VAD/turn detection, barge-in tuning, OpenCode
  Go streaming LLM, and a transcript-level `Marvi` wake gate.
- Local LiveKit Server start script and worker entrypoint.

## Still required before this phase can be marked complete

- Real speaker double-talk/barge-in test and unattended 60-minute soak.
- Replace the chunked Parakeet TDT baseline exception with a native stateful
  streaming recognizer that passes accented/owner-speech accuracy, the 300 ms
  median first-partial gate, and combined STT/TTS residency.

The 1 September follow-up also rejected Kyutai STT 1B: 46.63% accented-English
WER, 0.663 RTF, 1.434 s median first partial, 665 ms median EOS finalization,
and 3,058 MB incremental VRAM on the target RTX 3060.

The requested Whisper large-v3-turbo follow-up used WhisperLiveKit's pinned
AlignAtt SimulStreaming path and was also rejected: 36.80% WER, 2.747 RTF,
2.530 s median first stable partial, 288 ms median EOS finalization, and 1,865
MB incremental VRAM. No runtime adapter was added.

## Hardware bakeoff evidence

[`../evidence/phase-3-hardware-bakeoff.json`](../evidence/phase-3-hardware-bakeoff.json)
records the earlier RTX 3060 baseline. With three diffusion steps, VibeVoice produced its
first PCM chunk in 0.735 s at 0.994 RTF and 2.683 GiB peak allocated VRAM.
Nemotron transcribed the synthesized 5.333 s sample in 3.024 s (0.567 RTF),
correctly recovering “Marvi”; post-bakeoff GPU use was 4.245 GiB.

The current candidate measurements and exact source/model pins are recorded in
[`../evals/tts-candidates-2026-08-31.md`](../evals/tts-candidates-2026-08-31.md).
That evidence keeps Kokoro as default; adding an option to Settings is not a
substitute for the combined loopback and soak gate.

The 1 September streaming STT bakeoff is recorded in
[`../evals/stt-candidates-2026-09-01.md`](../evals/stt-candidates-2026-09-01.md).
Qwen's Rust rolling server led its accented-English slice at 20.23% WER but was
slower than realtime on the available native CPU build. Nemotron 3.5 was the
best GPU compromise at 30.06% WER and 0.099 RTF, but missed the first-partial
gate at 1.065 seconds. No STT candidate was promoted.
