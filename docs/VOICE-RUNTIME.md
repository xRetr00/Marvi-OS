# Native Windows Voice Runtime

## Selected bakeoff stack

Marvi OS uses the official LiveKit Agents session pipeline with local model
adapters:

- **STT:** NVIDIA Nemotron 3.5 ASR Streaming 0.6B, exported to ONNX by the
  pinned `altunenes/parakeet-rs` repository and executed through the upstream
  `parakeet-rs` crate. It is stateful, cache-aware, 16 kHz, and runs with an
  explicit `tr-TR` language hint.
- **TTS:** Microsoft VibeVoice Realtime 0.5B with 24 kHz streamed audio chunks
  and three diffusion steps, selected by the native hardware bakeoff.
  The LiveKit `StreamAdapter` sends completed sentences while generation and
  playout are incremental. Default voice: `en-Carter_man`.
- **Turn handling:** Silero VAD, local LiveKit multilingual turn detector,
  interruption enabled, and WebRTC capture/playout for AEC.

Kyutai TTS remains documented as an upstream reference, but the current 1.8B
runtime's practical VRAM and Windows support do not fit the RTX 3060 12 GB
combined STT/TTS budget. Whisper and batch-only STT are rejected.

## Installation and checks

Run `marvi setup voice`. It downloads immutable Hugging Face
revisions into `%LOCALAPPDATA%\Marvi-OS\models`, copies the official VibeVoice
voice presets, and verifies every core payload against `config/voice-models.json`.
Use `marvi models verify voice-stt` (or `voice-tts`) for a later integrity
check; `marvi doctor` runs the same check across everything.

Build the native STT bridge with:

```powershell
cargo build --release --manifest-path services/voice-runtime/Cargo.toml
uv sync --project services/agent --dev
```

Start the local room server with `scripts/start-local-livekit.ps1`, then run the
worker from `services/agent` with `uv run python -m marvi_agent.session dev`.
The official LiveKit agent console can exercise the real microphone/speaker
path without the Electron renderer while the desktop room client is developed.

## Available VibeVoice presets

The check script prints the authoritative installed list. The pinned upstream
currently includes Carter, Davis, Emma, Frank, Grace, Mike, Samuel, and paired
German, French, Italian, Japanese, Korean, Dutch, Polish, Portuguese, and
Spanish presets. It does not contain a Turkish voice; Turkish input is supported
by STT, while TTS voice/language quality needs explicit acceptance testing.
