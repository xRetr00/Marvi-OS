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

Phase 2 desktop implementation is in progress. The Electron control center,
recessed always-on Island, purpose-sized Windows icons, Marvi Gateway health
facade, and LiveKit worker configuration have runnable scaffolds and tests.
They are not yet a complete voice assistant. The next hard gate remains a
native-Windows streaming STT/TTS bakeoff on an NVIDIA RTX 3060 with 12 GB VRAM.

Current implemented desktop surfaces:

- tray-owned application lifetime and control-center window;
- sidebar, persistent status bar, overview, and About build information;
- Collapse + JetBrains Mono monochrome design system;
- passive `76×8` top-edge Island seed that expands for active voice states;
- canonical app icon rendered in the app, tray, taskbar/package, sidebar, and About.

## Developer start

```powershell
npm install
npm run icons
npm run dev
```

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
- [`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md) — detected target hardware and toolchain.
- [`docs/UPSTREAM.md`](docs/UPSTREAM.md) — adopted repositories, licenses, and update policy.
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — durable architectural decisions.

## Version

The current development version is stored in [`VERSION`](VERSION). Marvi OS
uses SemVer for product releases and records the exact Git commit in every
build. The update mechanism follows Marvi/Hermes' repository-owned Windows
handoff model; see the architecture document for the update contract.
