# Marvi OS

![Marvi OS repository banner](assets/marvi-os-banner.png)

Marvi OS is a local-first, always-on Windows voice and vision assistant. Its
primary interface is a compact Dynamic Island; its main window is a monochrome
control center for settings, integrations, memory, activity, room state,
updates, and About.

The repository banner is repository artwork only. It must never be embedded in
the desktop application. The desktop icon source is
[`assets/app-icon-source.png`](assets/app-icon-source.png).

## Status

Phases 2 and 4 are complete and Phase 3 is in hardware acceptance. The
native-Windows stack runs Nemotron 3.5 streaming ASR through `parakeet-rs`,
VibeVoice Realtime 0.5B, an official LiveKit `AgentSession`, and an Electron
LiveKit microphone/playout participant. The remaining Phase 3 gate is a real
loudspeaker double-talk test plus the 60-minute duplex soak.

Current implemented desktop surfaces:

- tray-owned application lifetime and control-center window;
- sidebar, persistent status bar, overview, and About build information;
- Collapse + JetBrains Mono monochrome design system;
- passive `76×8` top-edge Island seed that expands for active voice states;
- canonical app icon rendered in the app, tray, taskbar/package, sidebar, and About.
- action, notification, error, confirmation, and persistent YOLO Island states;
- Gateway-backed confirmation mode plus monitor/alignment placement controls.
- pinned model downloads, integrity checks, 25 TTS voices, and repeatable RTX
  3060 latency/VRAM evidence;
- local LiveKit room credentials, hidden development lifecycle, WebRTC AEC,
  streamed STT/TTS, local wake gating, and authoritative Island voice states;
- a structured tool router with exact-argument, single-use confirmation tokens
  that reject replay and argument mutation, plus an append-only local audit that
  records YOLO executions identically to confirmed ones;
- spoken and Island approval resolving the same token, and a Smart Room sidecar
  connection that degrades to stale reads without disturbing conversation;
- filtered room event history plus Island micro-events that expand the seed
  briefly and can never overwrite a live voice turn or steal focus.

## Developer start

```powershell
npm install
npm run icons
npm run dev
```

Before the first voice run, copy `services/agent/.env.example` to `.env`, add
the OpenCode Go key, and run `scripts/setup-voice-models.ps1`. See
[`docs/VOICE-RUNTIME.md`](docs/VOICE-RUNTIME.md) for the native build and checks.

Gateway and agent dependencies are isolated in the root `uv` workspace. These
commands are development tooling only; the shipped product has no CLI.
`npm run icons` requires ImageMagick and regenerates all runtime/package icon
sizes from `assets/app-icon-source.png`; generated icon files are committed.

## Foundation

- LiveKit Agents and a locally managed LiveKit transport.
- Continuous full-duplex capture/playout with local turn detection and WebRTC AEC.
- A local service facade branded **Marvi Gateway**.
- Local wake word, microphone, camera, presence, gesture detection, STT, and TTS.
- OpenCode Go as the cloud LLM provider.
- Composio SDK for connected accounts and actions.
- `D:\smart-room-plugin` as an independent room sidecar.
- Marvi Agent as an optional durable deep-work delegate.

Marvi OS adopts upstream projects before writing custom infrastructure. See
[`docs/UPSTREAM.md`](docs/UPSTREAM.md).

## Documentation

- [`AGENTS.md`](AGENTS.md) — mandatory rules for every coding agent.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — process and authority boundaries.
- [`docs/PLAN.md`](docs/PLAN.md) — phased delivery plan and acceptance gates.
- [`docs/phases/`](docs/phases/README.md) — phase-by-phase status, evidence, and commits.
- [`docs/IMPLEMENTATION-LOG.md`](docs/IMPLEMENTATION-LOG.md) — chronological work record.
- [`docs/UI.md`](docs/UI.md) — Dynamic Island and main-window design contract.
- [`docs/VOICE-MODEL-EVALUATION.md`](docs/VOICE-MODEL-EVALUATION.md) — native voice bakeoff.
- [`docs/VOICE-RUNTIME.md`](docs/VOICE-RUNTIME.md) — selected models, voices, setup, and diagnostics.
- [`docs/research/MIND-CORTEX-SOURCES.md`](docs/research/MIND-CORTEX-SOURCES.md) — reviewed proactivity and memory research.
- [`docs/REAL-AGENCY.md`](docs/REAL-AGENCY.md) — proactive mind and repository reuse contract.
- [`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md) — detected target hardware and toolchain.
- [`docs/UPSTREAM.md`](docs/UPSTREAM.md) — adopted repositories, licenses, and update policy.
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — durable architectural decisions.

## Version

The current development version is stored in [`VERSION`](VERSION). Marvi OS
uses SemVer for product releases and records the exact Git commit in every
build. The update mechanism follows Marvi/Hermes' repository-owned Windows
handoff model; see the architecture document for the update contract.
