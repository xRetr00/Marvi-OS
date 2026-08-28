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

Phases 2, 4, 5, 6, and 13 are complete. Phase 3 is in hardware acceptance,
Phase 7 has the update handoff working and a packaged installer building, and
Phase 8's vision ownership and contracts are complete with native camera
calibration still pending. The
native-Windows stack runs Parakeet TDT streaming ASR through ONNX Runtime,
Kokoro 82M, an official LiveKit `AgentSession`, and an Electron
LiveKit microphone/playout participant. The remaining Phase 3 gate is a real
loudspeaker double-talk test plus the 60-minute duplex soak.

Current implemented desktop surfaces:

- tray-owned application lifetime and control-center window;
- an experimental Marvi desktop pet rendered by a supervised native Windows
  helper, with state-driven animation, cursor gaze, a gray/blue/green/red
  status line, refined hover Voice/Activity controls, display/side/40–100%
  sizing, persistent drag placement, and Settings/tray visibility controls.
  Visible pet pixels capture pointer input while transparent gaps remain
  click-through. The measured helper uses 16.44 MiB private memory and no
  additional Chromium renderer. Full evidence is recorded in
  [`docs/phases/12-pet-companion.md`](docs/phases/12-pet-companion.md) pending a
  keep/draft decision;
- Lucide SDK-backed icon-led sidebar and controls, window-wide compact status
  bar with Marvi's live blue voice meter, overview, and About build/update
  information; no handwritten generic SVG icon paths remain;
- Collapse wordmark + readable JetBrains Mono monochrome design system;
- shared Provider, Chat, and Voice session telemetry for authoritative token
  deltas, turns, latency, and elapsed time;
- Gateway-owned Chat threads and branches with per-thread model routing,
  typed sources/files/images, local document extraction, Parakeet dictation,
  safe GFM/math rendering, segmented provider-backed context usage, thumbnail
  attachment tiles and image previews, validated generative widgets, read aloud
  through the standalone PocketTTS announcer, and a dedicated
  searchable conversation sidebar, compact human/assistant turn pairs, tool
  disclosures, source rows, and compact shell chrome adapted from an internal desktop;
- compact divided control surfaces across every non-Voice/non-Chat page, a
  tactile shared button language, an inset settings dialog with a persistent
  navigation rail, dedicated STT, TTS, Wake word, Appearance, and Preferences
  destinations, a collapsible branded sidebar, consistent control tooltips, and
  audible desktop haptics;
- passive `76×8` top-edge Island seed that expands for active voice states;
- canonical rounded app icon rendered from purpose-sized assets in the desktop,
  bootstrapper, tray, taskbar/package, shortcuts, sidebar, and About; external
  connector and provider identities use offline TheSVG brand marks;
- action, notification, error, and confirmation Island states with automatic
  terminal collapse and stale-control cleanup when the Gateway is unavailable;
- an idle Island that always recesses to its seed, with global YOLO and sensor
  state kept in the control-center status surfaces instead;
- Gateway-backed confirmation mode plus monitor/alignment placement controls.
- pinned model downloads, integrity checks, 25 TTS voices, and repeatable RTX
  3060 latency/VRAM evidence;
- local LiveKit room credentials, hidden development lifecycle, WebRTC AEC,
  streamed STT/TTS, local wake gating, and authoritative Island voice states;
- a structured tool router with exact-argument, single-use confirmation tokens
  that reject replay and argument mutation, plus an append-only local audit that
  records YOLO executions identically to confirmed ones;
- Gateway-owned cron jobs with durable one-shot,
  interval, and cron schedules; per-job provider/model/reasoning and tool
  controls; bounded agent execution through the existing audited tool router;
  repeat limits, run history, local output, and a transport-neutral seam ready
  for future messaging delivery;
- spoken and Island approval resolving the same token, and a Smart Room sidecar
  connection that degrades to stale reads without disturbing conversation;
- filtered room event history plus Island micro-events that expand the seed
  briefly and can never overwrite a live voice turn or steal focus;
- built-in Composio Connect lifecycle (connect, reconnect, enable/disable, and
  revoke), dynamic account-tool discovery behind per-toolkit read/write/admin
  ceilings, and nonce-delimited untrusted reads; remote writes remain confirmed,
  audited, and deduplicated;
- one selected durable-memory provider—Marvi's local SQLite store (default),
  pinned four-operation Mem0, or managed/self-hosted Honcho—with shared
  observe, recall, inspect, forget, and clear behavior; externally sourced
  entries retain an untrusted boundary and provider stores are never merged;
- a knowledge graph, recall-based reinforcement, reflection that promotes
  repeated episodes into durable facts, and a consolidation pass that forgets
  only what was never useful, presented as ARC with an Obsidian-style PixiJS +
  d3-force local memory graph, provenance tree, explicit-connection view, and
  shared Chat/Voice `memory_recall` tool; every LLM-assisted mind/reflection
  call uses its Models → Auxiliary role with content-free route/latency/usage
  diagnostics;
- native Gmail, Google Calendar, Slack, Notion, GitHub, and Google Drive memory
  providers with per-connection cursors, content-aware deduplication, visible
  sync health, manual sync, and realtime Composio triggers entering ARC as
  untrusted events without blocking the voice path;
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
- proactive speech and Chat Read Aloud through a cancellable CPU PocketTTS
  announcer that plays directly to the selected Windows output without opening
  Voice; a content-free playback marker suppresses wake scoring so Marvi does
  not wake herself;
- an independently updated Smart Room sidecar as the sole camera/vision owner:
  local face, gesture, posture, and visitor logic publishes bounded facts and
  events plus an on-demand compressed preview through authenticated Gateway
  contracts; the desktop has no direct plugin connection. Room exposes the
  sidecar's complete power, brightness, white-temperature, RGB, and mode
  controls, while Vision provides preview-led owner enrollment and face review;
- a protected sleep mode where the only thing Marvi may do to a sleeping room is
  switch a light off — enforced at the room boundary, and not overridable by
  YOLO.
- hidden-titlebar control center with renderer-painted page chrome, native
  Windows controls, Electric Gaze local backdrop, translucency lever,
  haptics, shell context menu, connecting and boot-failure overlays, and a
  voice-level meter in the status bar (see `feat/desktop-shell-ui`).
- tag-driven releases: `scripts/release.ps1` cuts `v<semver>` tags and the
  `Release` workflow gates them. There is no per-release installer — the
  bootstrap (`apps/updater`) clones the tag and builds it on the machine, so
  the tag is the payload. Its Windows handoff avoids pinning build output,
  presents real stages separately from optional live output, preserves failed-
  update diagnostics on screen, and closes automatically only after verified
  success. The desktop checks quietly and shows the exact available commits
  before handoff. See `docs/INSTALLER.md`.

## Developer start

```powershell
npm install
npm run icons
npm run dev
```

Before the first voice run, copy `services/agent/.env.example` to `.env`, add
the OpenCode Go key, and run `marvi setup voice`. Accounts accepts the Composio
project key directly in the control center, validates it before saving it in
Marvi's local provider settings, and then creates hosted Connect Links;
provider OAuth credentials remain in Composio and never enter Marvi OS.
`COMPOSIO_API_KEY` remains supported for managed installs. Optional signed webhooks use
`COMPOSIO_WEBHOOK_SECRET`; the local runtime otherwise consumes Composio's
realtime trigger stream. See
[`docs/VOICE-RUNTIME.md`](docs/VOICE-RUNTIME.md) for the native build and checks.

Gateway and agent dependencies are isolated in the root `uv` workspace. These
commands are development tooling only; the shipped product has no CLI.
`npm run icons` requires ImageMagick and regenerates all rounded desktop,
bootstrap, renderer, taskbar/shortcut, and tray sizes from
`assets/app-icon-source.png`. Small Windows frames are sharpened separately and
generated icon files are committed.

## Build and release

Local Windows packaging check (never publishes):

```powershell
.\scripts\build-desktop.ps1            # full: typecheck + tests + installer
.\scripts\build-desktop.ps1 -SkipTests # faster iteration
```

Diagnostic package artifacts land in `apps/desktop/dist/`. They are not release
payloads; published releases contain the bootstrap and its checksum.

Releases are tag-driven. From a clean `main`:

```powershell
.\scripts\release.ps1                 # prerelease -> stable, then patch bumps
.\scripts\release.ps1 -Bump minor     # or minor/major
.\scripts\release.ps1 -Version 1.2.3  # explicit
```

The script bumps `VERSION` (the single version source) plus both
`package.json` mirrors and the bootstrap crate, commits, creates an SSH-signed
annotated `v<version>` tag, verifies it against `.github/allowed_signers`, and
pushes main plus the tag.

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
- [`docs/RFC-NATIVE-CONNECTORS.md`](docs/RFC-NATIVE-CONNECTORS.md) — draft research and open questions for a Claude-like Marvi Connectors and Plugins layer.

## Version

The current development version is stored in [`VERSION`](VERSION). Marvi OS
uses SemVer for product releases and records the exact Git commit in every
build. The update mechanism follows the repository-owned Windows handoff model;
see the architecture document for the update contract.
