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
