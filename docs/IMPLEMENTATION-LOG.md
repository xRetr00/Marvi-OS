# Implementation Log

This is the chronological record of work that has actually happened. Planned
work belongs in `docs/phases/`; architectural decisions belong in
`docs/DECISIONS.md`.

## 2026-08-16 — repository foundation

- Created the independent `D:\Marvi-OS` Git repository as `marvi-os`.
- Added the product, architecture, UI, upstream, environment, and voice-model
  evaluation contracts.
- Adopted an Electron Vite React/TypeScript desktop scaffold instead of writing
  Electron process plumbing from scratch.
- Added the first main control-center shell, sidebar, persistent status bar,
  About placeholder, tray lifetime, and always-on Island surface.
- Added a minimal Python Marvi Gateway health facade and LiveKit worker
  configuration scaffold.
- Added initial behavior tests and verified typecheck, tests, lint, build, and
  dependency audit.
- Recorded as Git commit `24ca7af` (`feat: bootstrap Marvi OS foundation`).

## 2026-08-16 — Marvi design alignment and native Island correction

- Reviewed `D:\hermes-agent\apps\desktop\AGENTS.md`, `DESIGN.md`, theme tokens,
  font declarations, the voice-Island renderer, and its Electron overlay.
- Identified the first Marvi OS Island defect: a fixed `356×78`, draggable,
  focusable host containing a fixed 340 px pill. The oversized native surface
  made the overlay read as a conventional window.
- Replaced the fixed host contract with validated, content-sized native bounds.
  The renderer reports actual pill dimensions; Electron adds only a 12 px
  transparent shadow inset, recenters the host, and clamps all values.
- Made the passive Island non-focusable, non-movable, click-through,
  taskbar-free, frameless, shadowless at the OS level, and fully transparent.
- Removed the draggable full-window button and native tooltip behavior.
- Synchronized preview state from the control center to the actual Island via a
  narrow preload bridge.
- Adopted Marvi's Collapse brand face and bundled JetBrains Mono faces, and
  aligned the shell with the flat, token-driven monochrome design contract.
- Added unit coverage for Island size validation and positioning.
- Verified the running native windows as `1180×760` for the control center and
  `174×54` for the ready Island. A desktop capture confirmed that pixels behind
  the utility surface remain visible outside the pill.

Validation evidence and the resulting commit are recorded in
[`phases/02-desktop-island.md`](phases/02-desktop-island.md).

## 2026-08-16 — Phase 2 recessed seed and icon milestone

- Matched old Marvi's passive Island behavior: a transparent `76×8` seed at the
  top edge, rendering only a breathing 34 px line until activity begins.
- Replaced runtime downsampling of the 1254 px source with deterministic
  renderer, runtime, tray, package PNG, and multi-resolution Windows ICO assets.
- Added the canonical icon to the sidebar and a real About surface with build
  and component information.
- Added README-maintenance and milestone-commit rules to `AGENTS.md`.

## 2026-08-16 — Phase 2 authoritative Island and settings

- Replaced preview-only Island IPC with a validated, Gateway-authoritative
  runtime snapshot shared by the control center and independent Island renderer.
- Added action, notification, confirmation, error, device-state, and persistent
  YOLO presentations without turning the overlay into a visible window.
- Bound approval and denial to the exact Gateway confirmation token and enabled
  pointer/focus only while that actionable prompt exists.
- Added real Gateway/component status, Confirm/YOLO settings, and display plus
  left/center/right Island placement controls.
- Added malformed-boundary, state, confirmation, YOLO, placement, and Gateway
  policy tests. Typecheck, 14 desktop tests, 6 Python tests, lint, and production
  build passed.
- Visually checked Overview and Settings at the target renderer geometry. The
  only browser-console entry was a harmless dev-only missing favicon; Electron
  uses its native window icon.
- Measured one development Electron instance (main window plus Island) at
  536.3 MB aggregate working set and 1.562 CPU-seconds over 5 seconds. This is a
  debug/Vite upper-bound, not a release performance claim. NVIDIA's process
  query showed the shared Electron GPU process but no dedicated CUDA allocation.
- Native close verification left the Electron root and one Island renderer
  alive, removed the control-center renderer, and produced no polling errors.
  Runtime broadcasts now guard destroyed windows; tray Open recreates a window
  if Windows destroys it and ordinary title-bar Close hides it.
- Documented event-driven agency and upstream selection: LiveKit foreground,
  Letta mind bakeoff, APScheduler initiative, and Composio/MCP actions. Deferred
  LangGraph and Temporal until a measured workflow needs them.

## 2026-08-16 — Phase 3 native voice implementation and bakeoff

- Reviewed the supplied ContextAgent, Galaxy, ProAgent, ProAgentBench,
  ProactiveAgent, Letta, and spoken-interruption sources and routed them to the
  later Mind/Cortex phases instead of coupling them to realtime audio.
- Selected and checksum-pinned Nemotron 3.5 ASR Streaming 0.6B plus VibeVoice
  Realtime 0.5B after native Windows trials; installed 25 official TTS presets.
- Built a thin Rust `parakeet-rs` CUDA sidecar, true LiveKit streaming STT
  adapter, incremental VibeVoice TTS adapter, local wake gate, Silero VAD,
  `TurnDetector v1-mini`, and current `TurnHandlingOptions` interruption policy.
- Added local room token issuance, Electron microphone publication with WebRTC
  AEC/noise suppression, remote audio playout, LiveKit state-driven Island
  updates, hidden development process startup, and startup retry behavior.
- Verified model hashes, CUDA load, local LiveKit transport, worker dispatch,
  and an actual synthesized-audio → Nemotron loopback. The tuned run measured
  0.735 s first TTS audio, 0.994 TTS RTF, 0.567 STT RTF, and 4.245 GiB combined
  post-run GPU use. Physical speaker double-talk and the 60-minute soak remain
  the acceptance gate, so Phase 3 is deliberately not marked complete.

## 2026-08-16 — Phase 4 tool router, confirmation tokens, and Smart Room

- Added a narrow structured tool router to Marvi Gateway. Tools declare exact
  argument names and types; unknown tools, missing/extra arguments, and wrong
  types are refused before a handler runs.
- Replaced the placeholder confirmation with exact-argument tokens: single-use,
  120-second TTL, bound to a canonical fingerprint of the issued arguments. A
  mutated approval burns the token rather than executing a different action.
  The Island now echoes back the arguments it displayed, so what the user saw is
  what executes.
- Added an append-only JSONL audit covering the full lifecycle including
  `argument_mismatch` and `expired`. YOLO executions are audited identically to
  confirmed ones.
- Connected the smart-room sidecar as a client of its existing authenticated
  loopback JSON-RPC. Device authority, credentials, and automations stay in the
  sidecar. Reads fall back to its on-disk snapshot while it is unreachable, and
  the auth token is re-read per call so a sidecar restart needs no Gateway
  restart.
- Registered five voice tools on the `AgentSession`, including spoken approval
  and denial that resolve the same Gateway token as the Island. Verified against
  livekit-agents 1.6.10 that `RunContext` and the token stay out of the
  LLM-visible schema.
- Corrected the light tool after a live failure: the sidecar's `set_light`
  accepts `color_temp`, not `scene` — `scene` is a label it derives.
- Wired the Room and Activity pages to live sidecar state and the real audit
  timeline.
- Verified against a live room runtime through a real `uvicorn` process: an
  approved token physically dimmed the bulb 100% → 30%, mutation returned 409,
  replay and forged tokens returned 404, and an unreachable sidecar degraded to
  stale reads without disturbing the Gateway or assistant phase. Evidence is in
  [`phases/04-tools-room.md`](phases/04-tools-room.md).
- 24 Gateway tests, 9 voice-tool tests against the real Gateway app, 16 desktop
  tests, ruff, ESLint, and typecheck all pass.

## 2026-08-16 — Phase 4 room events and Island micro-events

- Added room event history by tailing the sidecar's JSONL log; it exposes no
  events RPC. Only the tail is read, so cost does not grow with the log.
- Filtered the log against an explicit notable-event allowlist after measuring
  the real distribution: 446 of a 500-event sample were ambient
  `vision_identity_state`. Allowlisting means an unrecognised new type is missed
  rather than repeated at the user every second, which is the right failure for
  an always-on surface. Dropped `vision_gesture` after live output showed it
  bursting three times in fifteen seconds while carrying no useful text.
- Rebuilt event lines from the payload after finding the sidecar's `summary` is
  only a type label — `mode_changed` reports "mode changed" without the mode.
- Gave background events a dedicated `room_event` channel on the assistant state
  instead of reusing `phase`, so they cannot overwrite a live voice turn or a
  pending confirmation. The Island renders one only while idle, without
  controls, politely announced, expiring after 25 seconds.
- Made the first observation after startup establish a baseline only, after live
  output showed a fresh Gateway surfacing an event from hours earlier.
- Verified against the real event log through a `uvicorn` process: 147 ambient
  events suppressed, lines rendered as `Light on at 100% 6500K (manual)` and
  `Unverified entry: stale_owntracks`, `phase` and `caption` untouched while
  the event rode its own channel, and no stale flash on a fresh start.
- Phase 4 marked complete: 53 Python tests, 22 desktop tests, ruff, ESLint,
  typecheck, and the production build all pass.

## 2026-08-16 — Phase 5 world context, trust boundary, and memory

- Built the untrusted external content boundary first, because both halves of
  Phase 5 depend on it. Content is delivered inside an envelope whose delimiter
  is a per-envelope random nonce, so it cannot close the envelope and continue
  in instruction position. Injection-pattern detection reports to the audit and
  never sanitises; content is always preserved verbatim (ADR-015).
- Added external-write idempotency. Tools declare `external=True`; the router
  checks the key *before* asking for confirmation, so a duplicate never becomes
  a second decision about something already done. A failed write stays
  retryable, and YOLO removes the prompt but not the deduplication.
- Integrated the official Composio SDK behind a thin adapter, verifying the call
  surface against the installed 0.19.0 package and a live account rather than
  from memory. Reads are enveloped; writes are sensitive, external, confirmed,
  and deduplicated. Dead connections are refused before any network call.
- Ran the memory bakeoff and rejected both frameworks for now (ADR-014): mem0
  hard-depends on `openai`, `qdrant-client`, and `posthog` telemetry, and Letta
  carries 69 core dependencies plus `sentry-sdk` while being a server that
  duplicates Marvi Gateway. Shipped local SQLite + FTS5 instead — measured at
  12.94 ms median search over 10,000 entries, 1.90 MiB, 1.15 ms reopen, zero
  VRAM and zero new dependencies.
- Connected memory to the trust boundary: an untrusted-origin memory is stored
  with `trusted = 0` and re-enveloped on recall, so an injection cannot launder
  itself into instruction position by taking a detour through storage. Proved
  end to end with an attack carrying a literal `[END EXTERNAL DATA]`.
- Added Accounts and Memory control-center pages, an `accounts` runtime
  component, `recall`/`remember` voice tools, and the standing prompt rule that
  `[EXTERNAL DATA ...]` content is reported and never obeyed.
- Live evidence against the real account: 9 connections collapsed to 7 toolkits
  (4 connected, 3 stale), enveloped Gmail and Calendar reads through a real
  `uvicorn` process, and `slack`/`reddit` refused before any network call.
- 111 Python tests, 22 desktop tests, ruff, ESLint, typecheck, and the
  production build all pass. Phase 5 stays in progress: no real outbound write
  has been sent, and account event ingestion is not built.
## 2026-08-16 — Desktop shell UI/UX: frameless chrome and Hermes-adapted surfaces

- Removed the native Windows title bar (`frame:false`, `titleBarStyle:'hidden'`)
  and added a renderer-painted 40 px title bar: brand mark, current page,
  minimize/maximize/close controls, drag region, double-click maximize, and
  close-to-tray behavior. Window verbs are IPC with sender validation in main.
- Adapted from the Marvi/Hermes desktop shell (MIT, provenance in
  docs/UPSTREAM.md): glyph spinner (unicode-animations), decode-text CONNECTING
  overlay, boot-failure recovery overlay with diagnostics + retry, web haptics
  provider (web-haptics, AudioContext warm-up kept), shell context menu
  (radix-ui), translucency lever (0–100 → setOpacity, floor 0.3), and the
  Electric Gaze animated ASCII backdrop vendored locally (412 KB mp4 + poster).
- Status bar gained a live 8-cell voice-level meter; Settings gained an
  APPEARANCE section (translucency, backdrop mode, backdrop opacity).
- `npm run typecheck`: passed. `npm test`: 6 files / 29 tests passed, covering
  title bar controls, connecting overlay, boot failure diagnostics, glyph
  spinner fallback, decode prefix, and backdrop/translucency clamps.
- `npm run build`: passed; renderer bundle 1.89 MB (radix context menu +
  unicode-animations included), backdrop assets emitted locally.
- Headless Chromium evidence (mocked bridge) under ignored `output/evidence/`:
  frameless Overview with Electric Gaze visible through translucent panels,
  Settings appearance controls, About, and the CONNECTING boot overlay.
- Work isolated in `git worktree` branch `feat/desktop-shell-ui` off
  `origin/main`; the primary checkout with concurrent work was untouched.

## 2026-08-16 — Phase 5 completion, memory depth, and the tool set

- Closed the outbound gate with one real email through the full router path.
  Gmail returned id `1a008f2f91cc7f2f`; the duplicate was deduplicated. The
  requested `noreplay.coregram@gmail.com` sender is not a connected account and
  has no verified send-as alias, so the single authorised identity was used and
  the deviation recorded rather than worked around.
- Built account event ingestion: bounded polling, normalisation, deduplication
  by provider id, untrusted storage, and untrusted graph edges for senders. A
  provider outage is a no-op and one dead provider does not stop the others.
  Live: 20 items ingested, second poll skipped all 20, 18 entities built.
- Deepened memory to the shape the product actually needs — knowledge graph
  with cascading deletes, recall-based reinforcement, idempotent reflection
  that promotes repeated episodes to facts, and a consolidation pass that drops
  only stale, never-recalled episodes. 31 memory tests.
- Corrected ADR-014 with ADR-014a. The original evaluated Letta as a
  self-hosted memory server; the supported integration is
  `openai.LLM.with_letta`, which makes Letta the *LLM* and owner of memory
  blocks and sleep-time agents. The dependency argument does not apply to the
  cloud path, but routing conversation to `api.letta.com` still conflicts with
  local-first and displaces OpenCode Go, and no `LETTA_API_KEY` is configured.
  Letta stays a candidate for the mind, not the store.
- Added the tool set behind one policy (ADR-016): web search/fetch/extract with
  env-selected Brave or SearXNG, file/terminal/process tools gated on an
  allowlisted `MARVI_WORKSPACE_ROOT`, and MCP servers connected by the Gateway
  rather than attached to the Agent so they inherit confirmation and audit.
- Added an SSRF guard that resolves a host before deciding: loopback, private,
  link-local, and non-http schemes are refused. Verified live that it blocks
  the room sidecar on 127.0.0.1:17842 and the cloud metadata address.
- MCP JSON Schemas are mapped onto the router's exact-argument validation, so a
  third-party tool cannot smuggle an undeclared argument, and an MCP tool is
  sensitive unless it declares a read-only hint.
- 183 Python tests and 22 desktop tests pass; ruff, ESLint, typecheck, and the
  production build are clean. Live surface: 24 tools, 10 of them sensitive.
## 2026-08-16 — Build script and tag-driven release workflow

- `scripts/build-desktop.ps1`: local Windows build with the CI gates
  (typecheck, tests), electron-vite build, and electron-builder NSIS installer;
  verified end-to-end on the RTX 3060 host (96.5 MB setup exe in
  `apps/desktop/dist/`). Never publishes.
- `scripts/release.ps1`: cuts releases from a clean main — bumps `VERSION`
  (single source) plus both package.json mirrors, commits, tags `v<semver>`,
  pushes; the tag triggers the Release workflow.
- `.github/workflows/release.yml`: on `v*` tag push, guards tag/VERSION
  agreement, runs gates, builds the Windows installer with `--publish never`,
  and publishes a GitHub Release with the installer and channel yml;
  `workflow_dispatch` is a dry run (artifacts only).
- Moved the desktop app's runtime packages to devDependencies: the renderer,
  main, and preload are fully bundled by electron-vite, so no runtime
  node_modules are needed, and electron-builder's node-modules walker (which
  OOM'd following the npm-workspace symlink cycle) now packs nothing.