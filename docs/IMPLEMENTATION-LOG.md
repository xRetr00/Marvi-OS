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

- Reviewed `the predecessor assistant\apps\desktop\AGENTS.md`, `DESIGN.md`, theme tokens,
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
  checks the key _before_ asking for confirmation, so a duplicate never becomes
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

## 2026-08-16 — Desktop shell UI/UX: frameless chrome and the predecessor assistant-adapted surfaces

- Removed the native Windows title bar (`frame:false`, `titleBarStyle:'hidden'`)
  and added a renderer-painted 40 px title bar: brand mark, current page,
  minimize/maximize/close controls, drag region, double-click maximize, and
  close-to-tray behavior. Window verbs are IPC with sender validation in main.
- Adapted from the the predecessor assistant desktop shell (MIT, provenance in
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
  `openai.LLM.with_letta`, which makes Letta the _LLM_ and owner of memory
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

## 2026-08-16 — Browser tools and automation

- Added a Playwright-backed browser session behind the Gateway policy
  (ADR-017). Reading, link listing, and going back are ungated; clicking,
  typing, and submitting are sensitive and confirmed. Downloads and dialogs are
  cancelled rather than confirmed, and the session is off until `MARVI_BROWSER`
  enables it.
- Reused the Chromium already cached at `%LOCALAPPDATA%\ms-playwright` rather
  than pulling a browser download, and chose Playwright over an anti-detect
  stack because evading bot detection is not a default behaviour this product
  should acquire.
- Extracted the background loop thread into `marvi_gateway.background` so the
  MCP bridge and the browser share one pattern: the tool registry stays
  synchronous while async clients live on a loop that outlives a request.
- Page content is enveloped like any other external source. A browser page is
  the sharpest injection surface in the product because the agent reads
  attacker-authored text and holds the controls on the same surface, so the
  text is contained and the controls are gated.
- Live: real Chromium opened `example.com` enveloped with exactly one end
  marker; a DuckDuckGo search executed only after approval and returned pages
  mentioning the query; a 320 KB screenshot landed in the workspace root; and
  `browser_open` on `127.0.0.1:17842` was refused by the SSRF guard.
- 196 Python tests and 37 desktop tests pass; ruff, ESLint, typecheck, and the
  production build are clean. Live surface: 32 tools, 12 sensitive.

## 2026-08-16 — Phase 6 REAL-AGENCY mind and the Letta decision

- Built the event-driven mind described in `REAL-AGENCY.md`: a durable journal
  with fingerprint deduplication, the five proactivity conditions as ordered
  named rules, a surface ladder from silent to propose, and a mind turn that
  records trigger, rule, surface, provider, latency, and cost for every
  decision — including the decisions to stay quiet.
- Made restraint the default. An unknown event kind can never exceed Activity,
  untrusted content can never reach `propose`, quiet hours and absence downgrade
  speech, a live conversation is never talked over, and an exhausted daily
  budget produces silence rather than an exception.
- The LLM deliberation seam may only make a decision quieter. A model does not
  get to argue with the policy ceiling, and its cost counts against the same
  budget.
- Added APScheduler 3.11.3 with four guarded ticks. Pausing stops decisions but
  not observation, so resuming shows what was missed instead of a silent gap.
- Replaced the deprecated FastAPI `on_event` hooks with a lifespan handler so
  the schedule starts and stops with the Gateway and never orphans a scheduler.
- Evaluated Letta against the mind gates and rejected it (ADR-018). The
  measurements: its Docker path is explicitly no longer maintained, the
  self-hosted server wants Postgres with pgvector, `with_letta` cannot carry
  OpenCode Go because the model is configured inside the Letta agent, and
  sleep-time agents put the background budget outside Marvi's control. The
  deeper finding is a role mismatch — `with_letta` replaces the foreground LLM,
  while the mind is a background decider, so Letta was never an alternative to
  this layer.
- 229 Python tests and 37 desktop tests pass; ruff, ESLint, typecheck, and the
  production build are clean.

## 2026-08-16 — Proactive speech, live deliberation, and a phase split

- Split vision out of Phase 6 into a new Phase 8 so the proactive mind could be
  finished without waiting on camera work. Phase 6 is cognition only and is now
  complete.
- Gave `speak` a voice. Proactive announcements use kyutai PocketTTS on the CPU
  rather than the Phase 3 streaming stack, because a one-shot sentence has no
  first-token race and nothing to barge into (ADR-019). Measured 1.5 s to load
  and 0.811 RTF at 24 kHz on a single torch thread.
- Published announcements into the LiveKit room instead of the sound card. The
  microphone is always live for the wake word, so audio played outside the room
  would be transcribed as if the user had said it; inside the room the client's
  WebRTC AEC handles it. This is where Phase 6 reconnects to Phase 3.
- Attached OpenCode Go to the deliberation seam through the same
  OpenAI-compatible boundary the voice agent uses. Verified live: an alarm event
  produced "The bedroom alarm is going off." in 4.1 s, and that sentence is what
  gets spoken. A slower run exceeded the 20 s budget and fell back to the
  deterministic verdict, which is the designed degradation.
- Fixed a real bug the tests caught: the mind was speaking `verdict.detail`,
  which is diagnostic text about the rule ("ceiling speak"), not a sentence.
  Speech text and rule diagnostics are now separate, and only deliberation can
  phrase what is actually said.
- Speech failure degrades to the Island rather than losing the decision.
- Dropped the durable Marvi Agent job bridge from Phase 7 (ADR-020). Phase 7 is
  now the Windows update handoff and the first release.
- 247 Python tests and 37 desktop tests pass; ruff, ESLint, typecheck, and the
  production build are clean.

## 2026-08-16 — Phase 7 Windows update handoff

- Adapted the tested predecessor update handoff for Marvi OS. The script lives in the
  checkout so each update refreshes the updater itself, and the
  `cmd start /min powershell` wrapper is preserved because a bare detached
  PowerShell dies before `-File` is read.
- Made the safety ordering explicit: record the rollback commit before touching
  anything, fail closed if the app never exits, refuse a dirty tree rather than
  discard the user's edits, always write a result, always try to relaunch.
- Verified every path against a throwaway remote: up to date, dirty tree, a real
  update that moved HEAD and rebuilt, a failing build that rolled back to the
  working commit, and a live app that aborted the handoff without touching the
  checkout.
- Caught a real defect only live testing would find: Windows PowerShell 5.1
  writes a BOM with `-Encoding utf8`, and `JSON.parse` rejects it. Every update
  result would have been unreadable, so the user would have seen nothing at all
  after updating. Fixed on both sides with a regression test.
- Added an Updates page showing version, channel, self-update capability, and
  the last result, consumed once rather than re-announced on every launch.
- 247 Python tests and 48 desktop tests pass.
- Built the Windows installer end to end: 96.5 MB setup executable, and the
  unpacked build launched with six processes responding at 542.6 MB aggregate
  working set and exited leaving no strays. Cutting the tagged release is left
  to the user, since publishing is their decision.

## 2026-08-16 — Phase 8 vision and the branding cleanup

- Reviewed the room sidecar's vision pipeline for design and then built a
  different one. It is motion-gated so an empty room costs almost nothing,
  CPU-only so it never competes with the voice stack for VRAM, and
  owner-relative so a bad angle on the owner cannot manufacture a stranger.
- Visitor sightings queue with a cropped face and a timestamp and surface on the
  away → home edge, through the Phase 6 mind, where a visitor report is one of
  the few event kinds allowed to be spoken. Telling someone about a stranger
  while they are out is information they cannot act on.
- A lingering stranger is folded into one queue entry by comparing against
  queued embeddings, and approving a face enrols it so the same person is
  recognised rather than re-queued.
- Caught live: loading buffalo_l inside the capture loop consumed the whole
  observation window, so the first `observe` returned a single frame. The model
  is warmed before the clock starts. Verified afterwards at 4 frames captured,
  1 analysed, 3 skipped by the gate.
- Removed predecessor branding across 27 files. Generated dependency lockfiles
  retain upstream package identifiers, while the independent room sidecar now
  receives its Marvi-owned data path through `MARVI_PLUGIN_DATA`.
- 272 Python tests and 48 desktop tests pass.

## 2026-08-16 — Phase 8 completion and the sleep rule

- Ran the camera live in an empty room, twice: 6 frames each, 1 analysed, 5
  skipped, 83% gated, no faces and no thumbnails written. An empty room costs
  almost nothing, which was the point of the motion gate.
- Added the sleep rule (ADR-023). While the room is asleep the only permitted
  action is switching a light off; everything else is refused. It is enforced at
  the room boundary so it binds every caller, and it outranks YOLO — YOLO is a
  statement about prompting, not about consent while unconscious. Verified live
  against the real room in `focus` mode and simulated in `sleep`.
- The guard reads live state first and falls back to the last snapshot when the
  sidecar is unreachable, because a stale "awake" reading is the one error that
  would let Marvi act during sleep.
- Admitted the sidecar's gestures, but only when they carry a command. A bare
  gesture fires in bursts and means nothing; a gesture bound to a command is a
  deliberate instruction. Marvi consumes the sidecar's inference rather than
  running a second pipeline.
- Added a structural privacy test: the vision module must contain no HTTP
  client, socket, or upload path, so a future edit that sends a frame somewhere
  fails a test rather than passing review.
- Phase 8 marked complete. Two items are deliberately open and neither is
  effort-bound: recognition thresholds need the owner's own face to validate,
  and activity-inside-applications is a privacy decision and a subsystem of its
  own rather than a gap in this one.
- 290 Python tests and 48 desktop tests pass.

## 2026-08-16 — Fixed the connecting hang, added activity context and a VLM seam

- Found why the app hung on the connecting page, and it was not packaging:
  `current_status()` hardcoded `state="starting"`, while the overlay waited for
  `ready` or `error`. It could never arrive, so the shell hung in dev and in
  packaged builds alike. Overall state is now computed — `ready` when the
  Gateway is up, `degraded` when an optional subsystem is erroring.
- Fixed two more failures in the same path. The overlay now clears on anything
  other than `starting`/`offline`, instead of demanding a bare `ready` that any
  degraded subsystem would prevent. And a Gateway that never arrives surfaces as
  a boot failure after 30s rather than animating forever.
- Packaged builds never started the Gateway at all: the launcher was guarded on
  `is.dev`. It now locates the checkout by walking up for `services/gateway`
  rather than assuming a fixed depth, and reports a clear error when there is no
  checkout instead of leaving the shell connecting.
- Verified end to end on the packaged build: 7 app processes, 9 Gateway
  children, `/health` answering in about a second, overall state `degraded`,
  14 tools registered, LiveKit up.
- Added ActivityWatch as world context — window, browser tab, and idle. It sees
  the window, not the work, and does not pretend otherwise. Window and tab
  titles are enveloped as external content, because a web page chooses its own
  title and can therefore write whatever it likes into that field.
- Added a scene-description seam for a vision-language model. It is
  unconfigured, because OpenCode Go exposes 26 models and none accept image
  content — `mimo-v2-omni`, `qwen3.7-max`, `glm-5.3` and `gpt-5.6-luna` were all
  tried and all rejected an `image_url` part. It speaks the OpenAI-compatible
  vision shape and waits for a provider rather than faking the capability.
- Rewrote `updater.ts` after a scripted edit doubled its newlines and left a
  literal BOM inside a regex; the BOM check now compares a code point so the
  source carries no invisible character.
- 296 Python tests and 48 desktop tests pass.

## 2026-08-17 — Tauri bootstrap installer + updater

- Replaced the PowerShell update handoff with a small Tauri binary
  (`apps/updater`, `marvi-bootstrap.exe`): a thin GUI shell over a headless
  Rust core (`marvi-bootstrap-core`). It is both installer (clone + build +
  atomic swap) and updater (in-place with rollback), and copies itself to
  `%LOCALAPPDATA%\Marvi OS\bin` on install.
- Added the channel model: `release` (default, opt-out) follows the latest
  signed `v*` tag and never fast-forwards a branch; `dev` (opt-in)
  fast-forwards `origin/main`. Channels persist in the state dir and are
  toggled from the Updates panel.
- Fixed every defect found in review: read-only `check` mode (target + behind
  count, no quit), liveness-aware in-progress marker (dead/stale markers are
  cleared instead of wedging the UI), build-output snapshot/restore so a failed
  build cannot leave a half-written app, release-tag integrity verification
  (invalid signature refuses, unsigned warns + pins the tag commit), a
  concurrency guard, unified repo-root discovery, and one state-dir source of
  truth shared with `updater.ts`.
- The binary is named `marvi-bootstrap` rather than `marvi-updater` so Windows
  installer detection never auto-elevates it (a real problem surfaced when the
  crate's test harness, named `marvi_updater_core`, hit UAC error 740).
- Core logic is unit- and integration-tested against real `git` remotes with a
  fake build runner: up-to-date, fast-forward, rollback-on-failed-build,
  dirty-tree skip, latest-tag checkout, and install staging/refusal. The
  `check` mode was smoke-tested end-to-end through the compiled binary.
- `release.yml` now builds and publishes `marvi-bootstrap.exe` as a release
  asset; `scripts/build-updater.ps1` builds it locally.

## 2026-08-17 — orb + Dynamic Island, end to end

- Vendored the thinking-orbs geometry engine (MIT) into
  `renderer/src/orb/engine` and rewrote the component layer: the island orb
  maps Marvi's nine assistant phases to the nine dotted states and colors each
  per phase (blue voice, green action, amber alert, red error), and the Voice
  page gets a dense orange→red→pink→magenta particle sphere on a ground grid.
- Wired the live microphone level through LiveKit's `createAudioAnalyser` so
  the orbs breathe with real energy rather than a clock (a new `setVoiceLevel`
  store action streams `calculateVolume()` every 100ms).
- Removed the fake static wave bars and the in-window island preview; the
  Dynamic Island is now the live orb + copy in the always-on surface only.
- `docs/UPSTREAM.md` records the vendored engine and its one local change
  (dropped an unused `rMin` param).

## 2026-08-17 — The first real install, and what it exposed

v0.1.3 was the first release installed from the bootstrap on a machine that was
not the development machine. It produced thirteen reported problems, and
confirming them turned up five more. The pattern in almost all of them is the
same: a code path that only runs on a machine unlike this one, so nobody had
ever run it.

**`uv` and Node were never installed.** Both were found on `PATH` and skipped —
a deliberate choice that turned out to be wrong, because the `PATH` a
developer's terminal has is not the one a GUI-launched Electron inherits.
Marvi now installs its own copies regardless, and says out loud that it is
doing so when a copy already exists.

Making that change is what revealed the reason nobody had noticed: **the `uv`
install command had been broken since it was written.** It ran a PowerShell
one-liner through `cmd /d /s /c`, and Rust's argument escaping targets the C
runtime parser rather than `cmd`'s. The quoting arrived mangled and the command
failed in about a second — on a code path that never executed on any machine
that already had `uv`. PowerShell is now invoked directly, and
`crates/core/tests/toolchain_live.rs` performs a real download, because that is
the only kind of test that would have caught it.

**The installer stopped at "it builds".** A built checkout is not an
installation: there was no LiveKit server, no `marvi` command, and no shortcut.
`handoff.rs` now runs four steps after the build, on install _and_ on update
(an existing installation predates all of it, and updating is how those
machines get it): record the GPU answer, `marvi setup --essential`, write a
`marvi` shim and prepend it to `PATH`, create shortcuts. Each is best-effort
and reports what it did.

**Archive components.** The LiveKit catalog entry had no files, so it installed
nothing and said "nothing to download". `binary` now marks a component whose
payload arrives as an archive: downloaded, hash-verified, unpacked, archive
deleted, presence of the named file being what "installed" means. LiveKit
1.13.5 and the `buffalo_l` face model both use it — the latter previously left
InsightFace to fetch 290 MB silently on the first frame it ever processed.

**The installer said nothing while working.** `npm ci` and `uv sync` ran with
their output discarded, so the window showed one word for fifteen minutes and
then either finished or said `npm exited with 1`. Output is streamed line by
line into a log pane and the last 25 lines are carried into the error. The
window is also resizable, minimisable, has a title bar, and is no longer always
on top.

**Two log directories.** `apps/desktop/src/main/config.ts` still had
`'Marvi OS'` with a space while everything else had been moved to `Marvi-OS`,
so a running Marvi split its own logs across two folders and neither had the
whole story. There is one `stateDir()` now, and everything derives from it.

**The voice stack could not start.** The agent exited immediately on every
launch with `ValueError: ws_url is required, or set LIVEKIT_URL` — the shell
knew the URL and never passed it to the children. All three now receive one
`childEnv`.

**LiveKit was signing with the published `devkey` / `secret` pair.** The JWT
library warned about the six-byte HMAC key on every start, and that key guards
a room carrying the user's microphone and camera. A random 32-byte pair is
generated per installation and shared with the server (`--keys`), the Gateway
and the agent; a stored secret below 32 bytes is replaced rather than carried
forward.

**Things that claimed to be fine and were not.** A local provider reported
`CONNECTED` whenever it had a default URL, so a stopped Ollama looked healthy —
the endpoint is now probed and a dead one names itself. Five of nine components
reported "nothing to verify" because the check had never been written for
Python environments or commands. An unreachable optional room sidecar logged an
`ERROR` on every poll, burying the failures that meant something;
`Policy.optional` drops those to `INFO` without making them silent.

**The test suite was writing to the user's real installation.** Every test that
built the app or configured logging wrote into `%LOCALAPPDATA%\Marvi-OS\logs`;
one autouse fixture pinning `MARVI_HOME` covers all of them and every path
added later. Separately, the updater's refresh tests were downloading ~100 MB
of toolchain per run (82s to 2s once gated) and — once the handoff existed —
would have started editing the real `PATH` and Desktop.

**The bootstrap had no version.** It ships as its own binary and is the thing
that performs updates, so a user can be holding an older one than the release
they installed. It was pinned at `0.1.0` with no way to say so; it now carries
the product version, answers `--version` without a window, and CI refuses a tag
where the two disagree.

## 2026-08-17 — The UI was confidently wrong

Reported as "no scrollbars, the colors are broken, the texts are idiotic". All
of it was true, and almost all of it was one failure mode wearing several
costumes: **the app displaying something it had no basis for.**

**A third of every page was unreachable.** `.sidebar` and `.content` are grid
items, and a grid item defaults to `min-height: auto` — "never smaller than my
content". So a page taller than the window pushed both past the shell,
`body { overflow: hidden }` clipped the excess, and there was no scroll
container anywhere to reach it. Measured on a 720px window: 882px of content,
with the status bar sitting entirely below the fold. `min-height: 0` plus one
`.page-scroll` region fixes all seventeen pages, and the sidebar's seventeen
destinations now scroll too.

Scrollbars are styled and always visible. An overlay scrollbar that appears
only mid-gesture is indistinguishable from no scrollbar, and that is precisely
how a clipped page reads as a broken one.

**The "maze" was a fixed-width string.** `+------------------------------+`
appeared fifteen times as a literal thirty-two characters, so on any wider
panel it floated mid-page as a stray box — and two of them either side of a
section that happened to be empty (Setup, while the catalog loads) looked
exactly like what was reported. `AsciiRule` keeps real corner characters and
clips a long dash run to its container, which in a monospace face is an honest
character rule at any width. That is what the ASCII look was after.

**Text below the contrast floor.** `--ui-text-tertiary` was 2.31:1 against the
background — under the 3:1 minimum for even large text — and it was the colour
of the buttons. `--ui-text-secondary` was 4.44:1, just under 4.5, and it
carries almost every label in the app. Now 4.85 and 7.73. Sixteen labels were
9px with 0.16em tracking, which is a decorative size doing a legibility job.

**"MIC ON / CAM ON" with the Gateway offline.** `AssistantState.microphone`
and `.camera` were declared with defaults of `True` and **nothing ever assigned
them** — not in the Gateway, not in the desktop. So the status bar, the Island,
and Settings ("CAMERA: ALWAYS ON") all reported both devices live, permanently.
This is the one indicator a person checks to find out whether they are being
listened to, which makes it the worst possible place for a comfortable
assumption. The fields are deleted. `deviceState()` derives from the component
that owns the device and answers `unknown` when the Gateway cannot be reached.

**"VOICE READY" with the Gateway offline**, for two independent reasons. The
`voice` component was hardcoded to `starting` with the detail "native streaming
worker available" — forever, whatever was true — which is what made `VOICE
STARTING` in the status bar mean nothing; it now reports whether a session
could actually happen and names what is missing. And `OFFLINE_RUNTIME` reused
the _ready_ assistant state, so an unreachable Marvi said "Say Marvi".

**A 2.5 GB download that said only "WORKING".** No progress was plumbed at all:
the install endpoint blocks for the whole download and returned only when done.
The installer's `progress` callback now writes to a readout the `/setup` page
reports, and the panel polls it during an install. Components that were merely
not downloaded yet were also painted in the _error_ colour, which made a fresh
install look like a broken one.

`shell-layout.test.ts` locks the layout chain and the device honesty, since both
failures were invisible to every test that existed.

## 2026-08-17 — block-element loading and meter

- Added `AccordionLoader` (`components/ui/accordion-loader.tsx`): the █ ▓ ▒
  blocks slide over a ░ track with staggered timing, adapted from a
  user-provided shadcn-style example onto Marvi's plain CSS. It replaces the
  `GlyphSpinner` on the boot `ConnectingOverlay`.
- Reworked the status-bar `VoiceLevelMeter` onto the same block-element shade
  ramp (░ → ▒ → ▓ → █) so a meter reads as one continuous density instead of
  eight on/off cells.
- `accordion-loader.test.ts` covers the glyphs, track, and length override.

## 2026-08-21 — readable shell, update access, and session telemetry

- Replaced the overly decorative application typography with explicit roles:
  Collapse remains the MARVI wordmark while JetBrains Mono carries every
  heading, paragraph, control, and data value at readable sizes and spacing.
- Rebuilt the sidebar around a small custom abstract SVG icon language, clearer
  brand block, active rail, and useful collapsed state. No icon dependency or
  runtime asset was added.
- Kept the status-bar visual treatment and made its version label actionable.
  The popover shows build metadata, channel, updater state, and the guarded
  update handoff. About now owns the same full controls; the redundant Updates
  destination and upstream marketing copy were removed.
- Adapted the user-provided `MessageTiming` pattern to the renderer's existing
  plain-CSS system. Provider, Chat, and Voice share session tokens, turns, last
  latency, and elapsed time. Token counts use Gateway provider-total deltas;
  they are not estimated from message text.
- Added component/store coverage for streaming timing presentation, provider
  baselines, combined chat/voice turns, voice phase deduplication, and duration
  formatting.

## 2026-08-21 — approved card hierarchy and desktop haptics

- Applied the approved four-module Overview layout: Current State, Voice Path,
  Service Health, and Context. Status text now lives in labeled cards, badges,
  or bounded value cells rather than floating across the page.
- Kept Voice and Chat purpose-built. Every other page now starts with one
  compact icon/label lead card and follows with simple bordered values, lists,
  or controls instead of copying Overview's dashboard density everywhere.
- Replaced the sidebar's literal `[<]` / `[>]` control with a directional rail
  glyph. Chromium View Transitions animate the sidebar/content snapshots with
  compositor transforms; reduced-motion users skip the transition.
- Fixed silent Windows feedback. `web-haptics` was initialized with `debug:
false`, leaving Electron on a mobile-only Vibration API path. Its documented
  desktop audio-transducer path is now enabled, and rejected audio triggers are
  contained so device loss cannot interrupt a UI action.

## 2026-08-21 — shell-control and secondary-module polish

- Restored the canonical Marvi mark in the collapsed sidebar; a stale late CSS
  override had hidden the image while leaving its brand cell empty.
- Added one Radix-backed tooltip surface for ambiguous shell actions. Title-bar
  controls, the sidebar rail control, and navigation now expose the same help
  treatment to pointer and keyboard users while retaining accessible names.
- Replaced platform text glyphs in the frameless title bar and settings close
  action with a consistent purpose-built SVG family and complete hover, focus,
  active, close-danger, and reduced-motion states.
- Strengthened non-Voice/non-Chat pages with corner-marked lead modules,
  bounded active sections, indexed rows, and restrained interaction feedback.
  Overview remains the only dense dashboard; Voice and Chat remain unchanged.

## 2026-08-23 — durable usage source of truth

- Added a Gateway-owned, atomic JSON usage ledger with per-provider totals and
  UTC daily buckets. It stores counters only and survives process restarts.
- Connected direct LiveKit voice usage as deltas from the cumulative session
  event, preventing both missed voice turns and duplicate counts. Chat and
  background work record on their existing common provider-client path.
- Added the dedicated Usage settings page and removed duplicate totals from
  Providers. The page distinguishes installation-local tokens from optional
  provider-account spend/balance scopes and never displays missing data as zero.
- Implemented official collectors for OpenRouter, DeepSeek, DeepInfra, and
  optional OpenAI/Anthropic admin credentials. Unsupported account scopes are
  labelled plainly; no dashboard is scraped.
- Adapted the supplied contribution grid into a 365-day UTC usage map and the
  supplied loading reference into a deterministic Processing Card. The
  unrelated game mode, external brand, random progress, and extra dependency
  were deliberately not carried over.

## 2026-08-23 — state-driven Chat composer beam

- Adopted the maintained `border-beam` 1.3.0 React package unchanged and
  recorded its MIT provenance in the upstream ledger.
- Wrapped the existing Gateway-connected Chat composer in the monochrome line
  preset. The effect activates only for focus, entered text, or streaming; it
  does not invent work or replace operational status.
- Preserved the existing send, stop, Enter/Shift+Enter, session model, and
  reasoning-effort behavior while adding compact state labels and matching
  abstract send/stop icons.
- Verified the production build and keyboard-send path in Chromium at
  1440×900 with no browser console errors.

## 2026-08-23 — Assistant UI-inspired Chat surface

- Audited the local Assistant UI checkout at commit
  `105af3eaea2093df271d9c44642e1c04d5f5cf7c` and adapted its frontend
  composition without importing its competing thread runtime or Tailwind kit.
- Rebuilt Chat around a bounded thread viewport, sticky action composer,
  right-aligned user turns, unboxed assistant replies, hover/focus copy actions,
  transcript export, local starter prompts, and pinned scroll restoration.
- Retained Marvi's existing streaming, cancellation, confirmation, session
  telemetry, provider/model override, reasoning, and tool-result behavior.
- Documented the separate backend plan for real threads, branches,
  attachments, typed content parts, follow-up suggestions, and shared-STT
  dictation. No backend code changed in this milestone.
- Visually verified populated and empty states at 1440×900 and the shipping
  1180×760 window size, including the model picker and scroll-to-latest control.

## 2026-08-23 — authoritative rich Chat contract

- Replaced the single-transcript assumption with Gateway-owned SQLite threads,
  message ancestry, preserved edit/regenerate branches, and per-thread
  provider/model/effort selection exposed through narrow Electron IPC.
- Added ordered typed message parts and local attachment lifecycle. Images are
  capability-checked and translated for OpenAI Chat, OpenAI Responses, and
  Anthropic; supported documents are extracted locally through MarkItDown and
  wrapped as untrusted external content.
- Adapted chat microphone PCM to the Agent-owned Parakeet TDT ONNX recognizer
  through bounded Gateway sessions. The renderer still performs no inference
  and microphone audio is not persisted.
- Replaced the handwritten Markdown subset with the maintained React Markdown
  pipeline for GFM and math, then added structured code/table/source styling,
  attachment previews, thread controls, context detail, and clearer actions.
- Added local read aloud for settled assistant prose through a bounded LiveKit
  RPC. It reuses Marvi's configured Kokoro TTS and normal playout/interruption,
  omits code, URLs, reasoning, tools, and source bodies, and cancels on thread
  change without duplicating the reply in Voice history.
- Explicitly dropped dynamic follow-up suggestions from both backend and UI.
- After merging the Parakeet STT milestone, passed 797 Gateway tests, 106 Agent
  tests, 193 desktop tests, desktop typecheck, and the production build.
- Visually checked the empty, expanded-context, and thread-drawer states at
  1180×760 in Chromium; evidence is under `output/playwright/`.

## 2026-08-23 — updater directory-handle fix and terminal-state UI

- Prevented the Windows update handoff from inheriting a working directory
  inside `apps/desktop/dist`; the bootstrap also moves to the state directory
  before Tauri starts, protecting updates launched by older desktop builds.
- Reworked the bootstrap terminal states around the Marvi monochrome contract:
  clearer hierarchy, non-duplicative recovery guidance, selectable logs, and a
  full-size keyboard-accessible Close updater action on unsuccessful outcomes.
- Successful installs and updates now close automatically after a brief
  completion state. Failed, skipped, and aborted outcomes remain open until the
  user dismisses them.

## 2026-08-23 — Smart Room becomes the sole vision owner

- Reviewed the real sidecar-to-desktop route before changing presentation. The
  production path remains Smart Room state/events/RPC → `RoomSidecar` → Gateway
  runtime/tools/journal → existing Electron IPC → Room page and Dynamic Island.
  No plugin UI or renderer-to-plugin transport was introduced.
- Moved camera capture, owner/visitor identity, gesture/posture analysis, model
  downloads, visitor retention, and vision health into the independent Smart
  Room repository. Only bounded facts and structured events cross the plugin
  boundary; raw frames and embeddings do not.
- Removed Gateway's `VisionService`, face library, cloud frame-description path,
  vision models/components, storage paths, dependencies, and homecoming face
  scheduler. Visitor reporting now has one owner in the sidecar.
- Added read-only and identity-mutating plugin contracts separately so Marvi can
  permit observations while keeping enrollment/approval behind its normal
  confirmation or YOLO policy.
- Extended the existing Room page with camera, people/owner, activity/posture,
  gesture, and pending-visitor facts. Vision and device status are derived from
  Gateway health, while notable room events continue to feed the compact Island.
- Verified the Smart Room fixture suite, focused Gateway contracts, full desktop
  typechecking, and all Electron renderer/main tests. Native camera calibration
  and soak remain a hardware acceptance step.

## 2026-08-23 — reliable Chat controls and generative widgets

- Added a Gateway-validated, persisted widget vocabulary and deterministic web
  evidence mapping, adapting Assistant UI's generative-tool pattern without a
  second runtime or executable model-authored components.
- Replaced draft-character context guesses with provider-reported input/cache
  usage and catalog context-window facts; unknown data remains visibly unknown.
- Repaired native clipboard copy, regeneration through intervening tool rows,
  duplicate optimistic working output, common model math delimiters, attachment
  upload errors, and Parakeet cumulative transcript assembly for dictation.
- Removed provider/zero-token footer noise and rendered source, metric,
  comparison, table, timeline, weather, gallery, document, and status data in a
  single Marvi instrument-panel family.
- Passed 801 Gateway, 107 Agent, and 198 desktop tests plus desktop typecheck,
  lint on changed sources, and the production build. Playwright inspection at
  1180×760 caught and fixed the composer beam clipping the context popover;
  final evidence is `output/playwright/chat-widgets-context.png`.

## 2026-08-23 — Assistant UI card rebuild

- Replaced the rejected full-width instrument-panel presentation with the card
  anatomy in the pinned local Assistant UI source: compact rounded paper
  surfaces, soft inner fields, bounded widths, and progressive disclosure.
- Rebuilt sources as a collapsed evidence pill and card grid; gave metrics,
  comparisons, tables, timelines, specs, status, and galleries their own
  content-specific layouts without repeated widget-type banners.
- Reworked the transcript rhythm, user surface, and composer around Assistant
  UI's narrow thread and rounded input proportions while retaining every Marvi
  control and Gateway contract.
- Removed the superseded animated border dependency and its runtime treatment.
- Passed 803 Gateway, 107 Agent, and 199 desktop tests plus desktop typecheck
  and the production build; visually checked the thread, source disclosure,
  and context card at the shipping 1180×760 viewport.

## 2026-08-23 — conversation-first Chat workspace

- Adapted the conversation-first sidebar anatomy from the pinned upstream desktop
  at `61977bb4d6b97ab2aece57d2405fa2f0b19e3ae0` while retaining Marvi's existing
  Gateway thread actions and renderer state.
- Replaced the global control-center sidebar only while Chat is active with a
  searchable recent-thread index, new-chat action, row actions, export, and an
  explicit return to the control center.
- Removed the redundant Chat content header and tightened the transcript to
  640px with smaller messages, cards, controls, and composer proportions.
- Verified search filtering and the control-center return in Chromium at the
  shipping 1180×760 viewport; visual evidence is
  `output/playwright/chat-workspace.png`.
- Preserved the authoritative Chat session timing strip in a compact sidebar
  footer and passed the complete desktop suite, typecheck, and production build.

## 2026-08-23 — compact Chat turns

- Replaced the remaining oversized labeled message blocks with the actual
  upstream conversation anatomy: a compact human prompt surface followed by
  unboxed assistant prose and a quiet hover/focus action rail.
- Removed visible per-message `YOU` / `MARVI` headers while retaining accessible
  sender labels, then moved timestamps beside the message actions.
- Tightened the transcript and composer to a shared 560px register, 11px
  conversation type, 22px message actions, and 24px composer controls.
- Verified the production renderer at 1180×760; visual evidence is
  `output/playwright/chat-compact-thread.png`.

## 2026-08-23 — direct Chat and shell surfaces

- Removed the remaining Marvi-specific card skin from assistant output. Metrics
  and comparisons now use small flat divided fields; tool calls use transparent
  faded disclosure rows; evidence is a `Sources · count` disclosure with compact
  source rows instead of the `Web evidence` treatment.
- Adopted the upstream shell dimensions and ownership: a 34px hidden titlebar with
  Electron-native Windows controls and a 20px two-sided status bar.
- Preserved Marvi's Gateway data, tool results, source URLs, session state,
  settings action, health actions, and update popover behind the copied UI.
- Verified the result and expanded source interaction in Chromium at 1180×760;
  visual evidence is `output/playwright/chat-exact-surfaces.png`.

## 2026-08-23 — window-wide shell chrome

- Moved the status bar out of individual page content and into a dedicated
  bottom shell track, so one 20 px footer spans beneath both the active sidebar
  and the current page on control-center and Chat routes.
- Replaced compressed status strings and custom shell glyphs with the pinned
  upstream treatment: Lucide icons, readable label/detail pairs, 24 px titlebar
  actions, 13.9 px title glyphs, and restrained 120 ms color transitions.
- Kept Marvi's earlier blue eight-cell live voice-level meter as the explicit
  product-specific exception and retained every existing health/settings/update
  action behind the new presentation.
## 2026-08-23 — measured desktop pet prototype

- Added the supplied Marvi character as a packaged local v2 atlas and a
  separate click-through Electron surface; no Codex user-data dependency or
  runtime image generation was introduced.
- Mapped Gateway-authoritative assistant phases to authored animation rows and
  reduced main-process cursor coordinates to a transient 16-way gaze index.
- Added persisted visible/display/side/scale preferences. Hiding the pet
  destroys its BrowserWindow so disabled mode carries no pet-renderer cost.
- Added unit coverage, a native screenshot harness, and a repeatable packaged
  off/on measurement harness. On the named Windows host the pet added one
  renderer and 70.08 MiB average private memory; the native-resolution Canvas
  repeat showed no measurable CPU delta over 12 seconds.
- Left Phase 12 in progress pending the explicit keep/optimize/draft decision.

## 2026-08-23 — native desktop pet helper spike

- Replaced the experimental third Electron pet surface with a focused
  Rust/Win32 helper supervised by Electron main. The helper receives only phase,
  gaze, bounds, and exit commands over stdin and cannot access Gateway, tools,
  media, or durable state.
- Preserved the owned 8×11 atlas and exact animation/gaze mappings, added Windows
  reduced-motion handling, and changed the fresh-install default to a Codex-like
  50% (`96×104`) footprint with 40/50/70/100% choices.
- Added build/package integration, native timing tests, protocol/path tests,
  packaged visual capture, all-descendant resource measurement, and a crash
  isolation test that proved Marvi survives and restarts a terminated helper.
- The packaged helper measured 23.50 MiB working set, 15.64 MiB private memory,
  and 0.00% of one core over the 12-second sample. It adds one native process and
  zero Chromium renderers, reducing direct private cost 77.7% from the original
  70.08 MiB renderer result.
- Kept Phase 12 experimental pending a full voice-stack soak, DPI/display
  checks, and the product owner's keep/draft decision.

## 2026-08-23 — native pet status and hover controls

- Added a scaled transparent control strip beneath the unchanged pet atlas.
  The helper draws an authoritative gray/blue/green/red status line and reveals
  compact Voice and current-operation buttons only while hovered.
- Kept the native window non-focusable and click-through outside the exact two
  button circles. The helper emits bounded intents; Electron main owns showing
  the control center and routes Voice to Voice and Tasks to the existing
  Activity audit without inventing a new task subsystem.
- Added protocol validation, count/routing/geometry/hit-test coverage, packaged
  idle/hover visual capture, a native-click-to-Electron-window acceptance test,
  full desktop and Rust checks, and another forced helper restart test.
- The interactive helper measured 23.62 MiB working set, 16.44 MiB private,
  0.00% of one core, one native process, and zero extra Chromium renderers over
  the 12-second packaged sample. Phase 12 remains experimental pending the
  original soak/DPI gate and the product owner's keep/draft decision.

## 2026-08-23 — unified control-center surfaces

- Replaced the remaining loose terminal modules and decorative card stacks on
  every non-Voice/non-Chat page with one shared compact page, section, divided
  row, status pill, action, and empty-state component set.
- Rebuilt Settings as an inset responsive dialog with a persistent 208 px rail,
  sentence-case navigation, compact controls, and the same 880 px content
  register used by the control center. The title bar now owns sidebar collapse,
  while the canonical app mark remains visible in the 52 px compact rail.
- Preserved the existing Voice and Chat interaction layouts and all Gateway,
  provider, usage, schedule, plugin, skill, memory, room, and update contracts;
  the milestone is presentation-only.
- Visually checked Overview, Providers, Preferences, Usage, and the narrow
  settings layout at 1180×760 and 760×700. Desktop typecheck, error-only lint,
  production renderer build, `git diff --check`, and all 218 desktop tests pass.
