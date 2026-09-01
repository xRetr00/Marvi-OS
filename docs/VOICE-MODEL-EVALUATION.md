# Native Windows Full-Duplex Voice Evaluation

## Non-negotiable constraints

- Native Windows only; no WSL2 or Docker runtime.
- NVIDIA RTX 3060 with 12 GB VRAM.
- The microphone stays captured during assistant playback.
- STT and TTS must emit useful incremental results; sentence-at-a-time wrappers do not qualify as streaming.
- OpenCode Go is the only required cloud inference in the voice loop.
- There is no user-facing CLI. LiveKit CLI is development tooling only.

Full Kyutai Unmute is not a shipping candidate because its documented runtime targets Linux/WSL and at least 16 GB VRAM. Marvi OS instead reuses its best idea: continuously streaming audio through an interruptible STT -> LLM -> TTS pipeline, with WebRTC acoustic echo cancellation and concurrent capture/playout.

## Bakeoff result

### Streaming STT

1. **No new streaming STT is selected.** The 1 September 2026
   accented-English bakeoff found that the Qwen3-ASR Rust rolling path was most
   accurate at 20.23% WER, but its native CPU build was slower than realtime.
2. **NVIDIA Nemotron 3.5 ASR Streaming 0.6B is the best GPU challenger**, not a
   selected engine. Through the pinned `parakeet.cpp` CUDA runtime it measured
   30.06% WER and 0.099 RTF, but its 1.065 s median first useful partial missed
   the 300 ms gate.
3. **Parakeet Realtime EOU 120M and Qwen3-ASR causal are rejected for now.**
   They measured 34.46% and 37.98% WER respectively and also missed the partial
   gate. Official Qwen vLLM realtime is ineligible because vLLM has no native
   Windows runtime.
4. **Kyutai STT 1B is rejected.** Its official Moshi CUDA path was realtime at
   0.663 RTF with 3,058 MB incremental VRAM, but it ranked last at 46.63% WER,
   produced five empty hypotheses, and measured 1.434 s median first partial
   plus 665 ms median finalization after EOS.

The existing Parakeet TDT remains the explicitly permitted non-streaming
baseline exception until a genuinely streaming candidate beats it on Marvi's
accented and owner-speech corpus and passes the latency, loopback, and soak
gates. See [the pinned candidate report](evals/stt-candidates-2026-09-01.md).

Whisper, whisper.cpp, faster-whisper, and WhisperLive are rejected. Chunking a non-streaming encoder and revising overlapping windows is not the incremental, stateful STT architecture required for this product.

### Streaming TTS

1. **Kokoro-82M remains the current shipping default.** It is the measured
   low-residency baseline, not a claim that its submitted-utterance buffering
   satisfies the future full-duplex streaming gate.
2. **CuteTTS Distill and VoXtream2 are selectable experimental options.** Cute
   now maps its catalog entry to the upstream-bundled female reference and runs
   explicit voice-clone mode; its corrected smoke measured 392 ms first PCM and
   0.873 RTF. Neither option has completed listening, cancellation, combined
   voice residency, loopback, and soak acceptance.
3. **VoxCPM2 is rejected** for slower-than-realtime synthesis and inadequate
   shared-GPU headroom. Breeze-TTS-2.cpp and Gepard remain outside the supported
   native-Windows path.
4. **Kyutai delayed-stream TTS and Orpheus TTS 3B** remain parked because their
   deployment or runtime footprints do not fit this machine.

CTC-TTS-F was removed from the catalog, Setup, adapter, and tests after the
owner's listening trial. Its historical measurements remain in the dated
report only as rejected evidence.

Qwen3-TTS is rejected as too heavy for the always-resident budget. PocketTTS,
Chatterbox's official whole-waveform API, and other sentence-buffered engines
are rejected as future full-duplex defaults. CosyVoice is not a primary
candidate until its official path proves genuine incremental generation
without overlap stitching. See
[the dated TTS report](evals/tts-candidates-2026-08-31.md).

## Duplex architecture under test

The target is simultaneous capture and playback, not alternating record/play states:

1. Electron publishes the microphone to a loopback LiveKit room with WebRTC `echoCancellation` and `noiseSuppression` enabled.
2. STT consumes audio continuously, including while Marvi is speaking.
3. LiveKit VAD detects speech start and triggers interruption handling.
4. Interruption cancels both TTS generation and local playout; conversation history is truncated to what the user actually heard.
5. LiveKit's audio `TurnDetector(version="v1-mini")` runs locally on CPU to distinguish a pause from a completed thought. It must never silently select the cloud `v1` model.
6. Partial transcripts stream into diagnostics, but only stable/final user turns enter the LLM context.
7. Streaming LLM text is segmented by a bounded clause scheduler and fed into TTS without waiting for a complete response.
8. Tool work is cancellable or detached from speech so a barge-in never blocks the audio loop.

Enhanced LiveKit Cloud noise filters and adaptive interruption inference are out of scope. The baseline is browser WebRTC AEC/noise suppression plus local VAD and the local audio turn detector. Optional local acoustic processing may be evaluated only if real speaker-loop tests show the baseline is insufficient.

## Benchmark protocol

Pin every repository commit, package/model revision, dtype, and quantization. Use the same microphone, speakers, room, prompts, and audio corpus for every candidate. Include real loudspeaker playback so echo leakage is measured rather than hidden by headphones.

Measure:

- cold/warm start and idle RAM/VRAM;
- STT first stable partial and finalization latency;
- word and named-entity accuracy for clean, far-field, noisy, accented, Turkish, and English samples;
- TTS first playable frame, underruns, real-time factor, and long-turn drift;
- simultaneous capture/playout echo leakage and false interruption rate;
- acknowledgement/backchannel behavior versus genuine barge-in;
- speech-start-to-audible-stop latency, including queued audio flush;
- device switch, sleep/resume, sidecar crash/recovery, and a 60-minute soak.

## Acceptance gates

| Metric | Required |
|---|---:|
| Combined steady voice VRAM | `<= 9.5 GB` |
| Transient total VRAM | no OOM on the 12 GB card |
| STT first useful partial | `<= 300 ms` median |
| STT final after speech end | `<= 550 ms` median |
| TTS first playable audio | `<= 800 ms` median on RTX 3060; target `<= 300 ms` |
| User speech to audible playout stop | `<= 150 ms` median, `<= 250 ms` p95 |
| Double-talk | user speech remains intelligible while Marvi is playing |
| Echo behavior | no self-transcription in the reference speaker setup |
| Streaming playback | no sentence-boundary buffering architecture |
| Soak | 60 minutes with no monotonic RAM/VRAM growth |
| Runtime | native Windows without WSL/Docker |

The selected STT must materially beat current Marvi Parakeet on the user's real corpus. A candidate that wins latency but loses names, accents, or far-field speech does not pass.

## Adapter rule

Voice engines remain independent libraries/sidecars behind thin LiveKit STT/TTS adapters. LiveKit owns session, interruption, turn, and playout lifecycle. An adapter converts streaming frames/events and exposes health/metrics; it must not create a second audio scheduler. All adapter behavior requires unit tests plus a real loopback-room integration test.
