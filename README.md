# Marvi OS

![Marvi OS repository banner](assets/marvi-os-banner.png)

Marvi OS is a local-first, always-on Windows voice and vision assistant. Its
primary interface is a compact Dynamic Island; its main window is a monochrome
control center for settings, integrations, memory, activity, room state, and
About. Version details and update actions are available from the status bar
and About rather than a separate update page.

The repository banner is repository artwork only. It must never be embedded in
the desktop application. The desktop icon source is
[`assets/app-icon-source.png`](assets/app-icon-source.png).

## Status

Phases 2, 4, 5, and 6 are complete. Phase 3 is in hardware acceptance,
Phase 7 has the update handoff working and a packaged installer building, and
and Phase 8 is complete. The
native-Windows stack runs Nemotron 3.5 streaming ASR through `parakeet-rs`,
Kokoro 82M, an official LiveKit `AgentSession`, and an Electron
LiveKit microphone/playout participant. The remaining Phase 3 gate is a real
loudspeaker double-talk test plus the 60-minute duplex soak.

Current implemented desktop surfaces:

- tray-owned application lifetime and control-center window;
- icon-led sidebar, persistent status bar, overview, and About build/update information;
- Collapse wordmark + readable JetBrains Mono monochrome design system;
- shared Provider, Chat, and Voice session telemetry for authoritative token
  deltas, turns, latency, and elapsed time;
- a card-organized Overview plus editorial labeled page modules, an animated
  branded sidebar rail, consistent control tooltips, and audible desktop
  haptic feedback;
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
  briefly and can never overwrite a live voice turn or steal focus;
- connected-account context through the official Composio SDK, where every
  external payload arrives inside a nonce-delimited untrusted envelope and
  external writes are confirmed, audited, and deduplicated;
- local SQLite episodic and semantic memory with search, forget, and verbatim
  export, storing externally sourced entries as untrusted and re-wrapping them
  whenever they are recalled;
- a knowledge graph, recall-based reinforcement, reflection that promotes
  repeated episodes into durable facts, and a consolidation pass that forgets
  only what was never useful;
- account event ingestion that deduplicates by provider id and never blocks the
  voice path;
- a content-free, durable usage ledger shared by Chat, Voice, background work,
  and local models, with a dedicated Usage page and optional reconciliation
  against official provider account APIs;
- web search, fetch, and extract with an SSRF guard, plus file, terminal, and
  process tools confined to an allowlisted workspace root, and MCP servers
  routed through the Gateway so they inherit confirmation and audit;
- browser automation where reading a page is free and clicking, typing, or
  submitting asks first, page content is treated as untrusted, and downloads
  are refused;
- an event-driven mind that decides from a durable journal rather than a timer,
  where quiet hours, presence, cooldown, a live conversation, and a daily budget
  each downgrade or silence a proposal, and every decision records the rule
  behind it — including the decisions to stay quiet;
- proactive speech on a CPU model published through the LiveKit room, so Marvi
  can say something unprompted without borrowing the streaming voice stack or
  hearing itself;
- motion-gated CPU face recognition that knows the owner from a visitor, queues
  unfamiliar faces with a cropped preview and a timestamp, and reports them when
  you get home rather than while you are out;
- a protected sleep mode where the only thing Marvi may do to a sleeping room is
  switch a light off — enforced at the room boundary, and not overridable by
  YOLO.
- frameless control center with a renderer-painted title bar (brand, page,
  window controls), Electric Gaze local backdrop, translucency lever,
  haptics, shell context menu, connecting and boot-failure overlays, and a
  voice-level meter in the status bar (see `feat/desktop-shell-ui`).
- tag-driven releases: `scripts/release.ps1` cuts `v<semver>` tags and the
  `Release` workflow gates them. There is no per-release installer — the
  bootstrap (`apps/updater`) clones the tag and builds it on the machine, so
  the tag is the payload. See `docs/INSTALLER.md`.

## Developer start

```powershell
npm install
npm run icons
npm run dev
```

Before the first voice run, copy `services/agent/.env.example` to `.env`, add
the OpenCode Go key, and run `marvi setup voice`. Connected
accounts need `COMPOSIO_API_KEY` in the same file; Marvi OS reads it from the
environment and never stores a provider credential of its own. See
[`docs/VOICE-RUNTIME.md`](docs/VOICE-RUNTIME.md) for the native build and checks.

Gateway and agent dependencies are isolated in the root `uv` workspace. These
commands are development tooling only; the shipped product has no CLI.
`npm run icons` requires ImageMagick and regenerates all runtime/package icon
sizes from `assets/app-icon-source.png`; generated icon files are committed.

## Build and release

Local Windows build (gates + installer, never publishes):

```powershell
.\scripts\build-desktop.ps1            # full: typecheck + tests + installer
.\scripts\build-desktop.ps1 -SkipTests # faster iteration
```

Artifacts land in `apps/desktop/dist/` (NSIS setup exe + `latest.yml`).

Releases are tag-driven. From a clean `main`:

```powershell
.\scripts
elease.ps1                 # 0.1.0-dev.0 -> 0.1.0, then patch bumps
.\scripts
elease.ps1 -Bump minor     # or minor/major
.\scripts
elease.ps1 -Version 1.2.3  # explicit
```

The script bumps `VERSION` (the single version source) plus both
`package.json` mirrors, commits, tags `v<version>`, and pushes.

The `Release` workflow then runs every gate — desktop, gateway, agent and
bootstrap tests — and finally `npm run build:unpack`, which is the exact build
the updater performs on a user's machine. A tag that cannot be built is a tag
that breaks every Dev-channel update, and the failure would land on someone
else's computer rather than in the workflow.

It publishes `marvi-bootstrap.exe` and its checksum. An existing install
updates itself from the tag and downloads nothing; the bootstrap is only for a
first install. `workflow_dispatch` is a dry run: artifacts upload, no release
is created.

## Installing

Download `marvi-bootstrap.exe` from the latest release and run it. It installs
`uv` and Node, clones the tag, and builds it. Then:

```powershell
marvi status     # what is left to set up
marvi setup      # install what is missing
marvi doctor     # what is wrong, and what fixes it
```

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
- [`docs/CHAT.md`](docs/CHAT.md) — Chat frontend contract and backend capability plan.
- [`docs/VOICE-MODEL-EVALUATION.md`](docs/VOICE-MODEL-EVALUATION.md) — native voice bakeoff.
- [`docs/VOICE-RUNTIME.md`](docs/VOICE-RUNTIME.md) — selected models, voices, setup, and diagnostics.
- [`docs/research/MIND-CORTEX-SOURCES.md`](docs/research/MIND-CORTEX-SOURCES.md) — reviewed proactivity and memory research.
- [`docs/REAL-AGENCY.md`](docs/REAL-AGENCY.md) — proactive mind and repository reuse contract.
- [`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md) — detected target hardware and toolchain.
- [`docs/PROVIDERS.md`](docs/PROVIDERS.md) — model providers, API shapes, caching, and budget.
- [`docs/UPSTREAM.md`](docs/UPSTREAM.md) — adopted repositories, licenses, and update policy.
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — durable architectural decisions.

## Version

The current development version is stored in [`VERSION`](VERSION). Marvi OS
uses SemVer for product releases and records the exact Git commit in every
build. The update mechanism follows the predecessor assistant' repository-owned Windows
handoff model; see the architecture document for the update contract.
