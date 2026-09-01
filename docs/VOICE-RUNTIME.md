# Native Windows Voice Runtime

## Shipping stack and selectable TTS engines

Marvi OS uses the official LiveKit Agents session pipeline with local model
adapters:

- **STT:** Parakeet TDT 0.6B v3 through ONNX Runtime on CPU. The optional v2
  checkpoint locks recognition to English.
- **Default TTS:** Kokoro 82M, 24 kHz mono PCM, with clause-level incremental
  synthesis. Kokoro remains the safe default because it has the largest measured
  throughput and memory margin on the target RTX 3060.
- **Optional TTS:** CuteTTS Distill and VoXtream2. Each runs in its
  own `uv` project and long-lived child process. Only newline-framed requests
  and PCM chunks cross into the LiveKit Agent, preventing incompatible Torch,
  Transformers, Moshi, and codec pins from modifying the Agent environment.
- **Turn handling:** Silero VAD, LiveKit interruption/playout, and WebRTC
  capture/playout for AEC.

`config/tts-engines.json` is the shared engine/voice catalog. Settings persist
`MARVI_TTS_ENGINE` and `MARVI_TTS_VOICE`; the Gateway validates the voice
against the selected engine and the Agent repeats that validation before load.
Changing either choice takes effect for the next voice session.

## Installation and checks

Run the normal Setup flow for Kokoro and Parakeet. The optional engines appear
as separate runtime/model components so a user installs only the large stack
they intend to use:

```powershell
uv sync --project services/tts-cute
uv run --project services/tts-cute python -m marvi_tts_cute.setup

uv sync --project services/tts-voxtream
uv run --project services/tts-voxtream python -m marvi_tts_voxtream.setup
```

Setup pins the upstream source and model revisions. VoXtream Setup also loads
its upstream runtime once so Mimi and ReDimNet are cached before an offline
voice session.

Start the local room server with `scripts/start-local-livekit.ps1`, then run the
worker from `services/agent` with `uv run python -m marvi_agent.session dev`.

## Voice catalogs

- Kokoro: eleven American/British English speakers.
- CuteTTS Distill: the upstream package's bundled female reference recording,
  exposed as `Cute Reference`. Marvi always uses explicit voice-clone mode;
  reference enrollment is not exposed until there is an owned prompt flow.
- VoXtream2: twelve upstream reference clips across English, Arabic, Chinese,
  French, German, Hindi, Japanese, Portuguese, Russian, Spanish, and Swedish.

An engine being selectable is not a promotion to the shipping default. The
hardware acceptance gates in `docs/VOICE-MODEL-EVALUATION.md` still apply to
each option: listening, combined STT/TTS residency with 2 GB system headroom,
interruption, device switching, crash recovery, and the 60-minute soak.

On 2026-09-01 CuteTTS passed a corrected native-Windows synthesis smoke using
that exact bundled reference: 392 ms first PCM, 3.63 seconds wall time for 4.16
seconds of 24 kHz output (0.873 RTF), and 26 PCM chunks. This is process and
voice-selection evidence, not acoustic, interruption, or soak acceptance.
CTC-TTS-F was removed from the product catalog and Setup at the owner's
direction after hands-on testing; it is no longer a selectable engine.
