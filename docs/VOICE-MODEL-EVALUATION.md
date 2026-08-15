# Native Windows Full-Duplex Voice Evaluation

## Non-negotiable constraints

- Native Windows only; no WSL2 or Docker runtime.
- NVIDIA RTX 3060 with 12 GB VRAM.
- The microphone stays captured during assistant playback.
- STT and TTS must emit useful incremental results; sentence-at-a-time wrappers do not qualify as streaming.
- OpenCode Go is the only required cloud inference in the voice loop.
- There is no user-facing CLI. LiveKit CLI is development tooling only.

Full Kyutai Unmute is not a shipping candidate because its documented runtime targets Linux/WSL and at least 16 GB VRAM. Marvi OS instead reuses its best idea: continuously streaming audio through an interruptible STT -> LLM -> TTS pipeline, with WebRTC acoustic echo cancellation and concurrent capture/playout.

## Recommended bakeoff order

### Streaming STT

1. **Moonshine Voice Medium Streaming** — first candidate. It is a true incremental model, preserves encoder/decoder state between chunks, ships a native Windows C/C++ library and ONNX Runtime path, and can run on CPU so the GPU remains available for TTS and vision. Test Tiny/Small only if Medium misses the latency budget. The MIT license covers the code and English models; other-language model terms must be reviewed separately.
2. **sherpa-onnx streaming Zipformer/Paraformer** — packaging fallback. It has native Windows binaries, C++ and Node APIs, and real online decoding. Model quality must beat the current Marvi baseline on the user's microphone.
3. **NVIDIA Nemotron Speech Streaming 0.6B / cache-aware streaming Conformer** — quality challenger only if a stable native-Windows NeMo path fits the shared VRAM budget. It must show a material improvement over the existing Marvi Parakeet pipeline to justify its heavier runtime.
4. **Current Marvi Parakeet streaming stack** — measurement baseline only; observed recognition quality is not sufficient for selection.

Whisper, whisper.cpp, faster-whisper, and WhisperLive are rejected. Chunking a non-streaming encoder and revising overlapping windows is not the incremental, stateful STT architecture required for this product.

### Streaming TTS

1. **Kyutai delayed-stream TTS 1.6B** — first quality candidate. Evaluate its official fully streaming PyTorch path directly on native Windows. Do not adopt the full Unmute deployment or its Linux-oriented server stack.
2. **Microsoft VibeVoice-Realtime 0.5B** — first fallback. The upstream model accepts streaming text and targets approximately 300 ms first audible audio with a substantially smaller model. Prefer the official model/runtime; third-party Windows servers are evaluation references, not trusted product dependencies until audited.
3. **Orpheus TTS 3B** — research-only challenger. Its claimed low streaming latency is attractive, but the vLLM-oriented runtime and model size are a poor fit for a 12 GB card shared with vision. Test only if the first two fail quality.

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
| TTS first playable audio | `<= 300 ms` median |
| User speech to audible playout stop | `<= 150 ms` median, `<= 250 ms` p95 |
| Double-talk | user speech remains intelligible while Marvi is playing |
| Echo behavior | no self-transcription in the reference speaker setup |
| Streaming playback | no sentence-boundary buffering architecture |
| Soak | 60 minutes with no monotonic RAM/VRAM growth |
| Runtime | native Windows without WSL/Docker |

The selected STT must materially beat current Marvi Parakeet on the user's real corpus. A candidate that wins latency but loses names, accents, or far-field speech does not pass.

## Adapter rule

Voice engines remain independent libraries/sidecars behind thin LiveKit STT/TTS adapters. LiveKit owns session, interruption, turn, and playout lifecycle. An adapter converts streaming frames/events and exposes health/metrics; it must not create a second audio scheduler. All adapter behavior requires unit tests plus a real loopback-room integration test.
