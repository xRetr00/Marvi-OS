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

1. **Selected: NVIDIA Nemotron 3.5 ASR Streaming 0.6B through `parakeet-rs`.**
   This is the current multilingual cache-aware model, not old Marvi's Parakeet
   baseline. The pinned ONNX path loads natively with CUDA, accepts arbitrary
   feeds while preserving encoder/decoder state, and takes an explicit
   language hint (`en-US` by default).
2. **Moonshine Voice Medium Streaming** remains the CPU/packaging fallback if
   the real microphone corpus does not validate Nemotron quality.
3. **sherpa-onnx streaming models** remain a second packaging fallback.

Whisper, whisper.cpp, faster-whisper, and WhisperLive are rejected. Chunking a non-streaming encoder and revising overlapping windows is not the incremental, stateful STT architecture required for this product.

### Streaming TTS

1. **Selected: Microsoft VibeVoice-Realtime 0.5B.** The pinned official runtime
   emits acoustic PCM chunks, exposes 25 official presets, and passes realtime
   throughput at three diffusion steps on the target GPU.
2. **Kyutai delayed-stream TTS** is rejected for the active 12 GB/native-Windows
   stack: its current practical runtime budget and supported deployment path do
   not fit alongside ASR and later vision.
3. **Kokoro ONNX** was fast overall and exposes 54 voices, but its stream did not
   yield until synthesis of the submitted utterance completed. It is not the
   primary acoustic-streaming engine.
4. **Orpheus TTS 3B** remains parked because its runtime/model footprint is a
   poor fit for this machine.

Qwen3-TTS is rejected as too heavy for the always-resident budget. PocketTTS, Chatterbox's official whole-waveform API, and other sentence-buffered engines are rejected as the main voice because they cannot preserve full-duplex call behavior. CosyVoice is not a primary candidate until its official path proves genuine incremental generation without overlap stitching.

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
