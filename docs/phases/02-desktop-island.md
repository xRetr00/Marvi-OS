# Phase 2 — Desktop Shell and Dynamic Island

**Status:** complete
**Depends on:** Phase 1 status contracts for live data

This phase started early because the Dynamic Island is the product's primary
surface and its native-window behavior can be proven without the voice engine.

## Delivered

- Electron Vite React/TypeScript scaffold, tray lifetime, main window, sidebar,
  content area, status bar, and page shells.
- App icon used at runtime; repository banner excluded from runtime UI.
- Marvi-derived visual rules: flat hierarchy, one-pixel hairlines, restrained
  blue signal, Collapse branding, and JetBrains Mono system text.
- Recessed Marvi-style sleep seed: `76×8` transparent body at the top edge so
  only its short light line remains visible.
- Compact state-specific Island geometry: wake `180×34`,
  listening `210×38`, thinking `230×40`, speaking `250×42`.
- A dynamic native host that follows measured content with a small transparent
  shadow inset; bounds are validated in Electron before use.
- Transparent, frameless, click-through, non-focusable, non-draggable,
  always-on-top behavior for passive states.
- Control-center preview state synchronized to the independent Island renderer.
- Unit tests for malformed measurements, clamping, and display centering.
- Canonical rounded icon used in the sidebar, About, desktop, and bootstrapper,
  with generated 16–256 px ICO entries, a purpose-sized 16–32 px tray set,
  explicit shortcut icon selection, 256 px runtime/renderer PNGs, and a 512 px
  package PNG. The generator square-pads the source without distortion and
  tunes small Windows frames separately.
- About surface exposes version, commit, build time, target architecture,
  update channel, and current Gateway/LiveKit/voice component status.
- Gateway-authoritative projection for all passive, voice, action,
  notification, confirmation, and error states.
- Exact-token Island approvals and denials; pointer/focus is enabled only while
  an actionable confirmation is visible. Settled and expired prompts collapse
  automatically, Gateway loss removes stale controls, and every idle mode
  returns to the line-only seed.
- Settings for Confirm/YOLO mode and explicit display plus left/center/right
  Island placement, with accessible switch/pressed semantics.
- Real Gateway/component, microphone, camera, phase, mode, and version data in
  the persistent status bar.
- Icon-led sidebar navigation with a Marvi-specific abstract line language and
  Collapse restricted to branding so application text remains readable.
- Version status button with compact build/update details; About owns the full
  updater controls and the redundant Updates destination is removed.
- Shared session telemetry on Provider, Chat, and Voice: authoritative token
  deltas, combined turn count, last latency, and continuously elapsed duration.
- Four-module Overview dashboard with labeled cards and a simpler lead-card +
  value-row hierarchy across every non-Voice/non-Chat page.
- Directional sidebar rail control with compositor View Transition motion,
  reduced-motion fallback, and working desktop audio-transducer haptics.
- Canonical Marvi mark retained in the collapsed rail, shared accessible
  tooltips for ambiguous shell actions, modern abstract SVG window controls,
  and richer editorial module treatment on secondary pages.

## Design-source review

- `the predecessor assistant\apps\desktop\DESIGN.md`
- `the predecessor assistant\apps\desktop\src\styles.css`
- `the predecessor desktop's voice island`
- `the predecessor assistant\apps\desktop\electron\main.ts`

The old Marvi Island deliberately uses a fixed transparent stage to avoid
Windows resize animation jank. Marvi OS instead resizes only when content
dimensions change at state boundaries; CSS does not tween the Island's geometry.
This satisfies content-sized native bounds without resizing every animation
frame.

## Deferred to delivery phases

- Update execution is Phase 7; Phase 2 exposes complete build/update-channel
  metadata and an honest pending action rather than a fake updater.
- Voice device selection and model versions arrive with native adapters in
  Phases 3–4. Settings currently reports authoritative device state.
- Placement is session-scoped until the Phase 7 settings persistence schema;
  it already uses per-display work areas and Windows display scale.

## Acceptance evidence

- `npm run typecheck`: passed on 2026-08-16.
- `npm test`: 3 files / 8 tests passed on 2026-08-16.
- `npm run lint`: passed on 2026-08-16.
- `npm run build`: passed on 2026-08-16; all four font assets emitted.
- Native Windows inspection: the seed requests `100×32` host bounds (`76×8`
  content plus transparent inset); Win32 reports a `100×39` DWM outer rect.
  A desktop capture confirms the host is transparent and only the `34×2`
  blue-white line is painted at the work-area edge.
- About/sidebar visual inspection passed at the `1180×760` target viewport;
  both render the canonical icon without the repository banner.
- `electron-builder --dir` produced the Windows x64 unpacked application. The
  icon extracted from `Marvi-OS.exe` is the expected 32 px Marvi source, and the
  ICO contains 16, 24, 32, 48, 64, 128, and 256 px entries.
- Renderer screenshots: main shell and ready Island checked at actual target
  geometry on 2026-08-16; artifacts remain local under ignored `output/`.
- Commits: `24ca7af` (initial shell), `fb2178b` (design/dynamic bounds), and
  current milestone subject `feat: add recessed island and app identity`.
- `npm run typecheck`: passed on 2026-08-16 after the runtime bridge.
- `npm test`: 4 files / 14 tests passed on 2026-08-16, including malformed
  Gateway snapshots, confirmation states, YOLO, and three alignments.
- `uv run pytest -q`: 6 Gateway/agent tests passed on 2026-08-16, including
  Gateway-owned mode and exact-token confirmation behavior.
- Playwright visual inspection passed for Overview and Settings at the target
  renderer geometry; local artifacts are under ignored `output/playwright/`.
- Focused renderer ESLint, typecheck, and 167-test suite passed for the
  navigation/update/session-telemetry refinement on 2026-08-21.
- Production build, focused renderer ESLint, and 172 tests passed for the
  approved card hierarchy, sidebar transition, and haptics repair on 2026-08-21.
- Production build, focused renderer ESLint, and 174 tests passed for the
  shell-control/secondary-module polish on 2026-08-21. Playwright inspection
  covered expanded Overview, collapsed logo/navigation tooltip, Room, and
  Maintenance at 1920×1040 with zero browser errors or warnings.
- Development Electron upper-bound (main + Island): 536.3 MB aggregate working
  set and 1.562 CPU-seconds over 5 seconds. No dedicated CUDA allocation was
  reported; release idle profiling remains a Phase 7 optimization gate.
- 2026-08-29 identity refresh: regenerated the desktop, bootstrap, tray,
  taskbar/shortcut, and renderer assets from one rounded square master; static
  tests verify PNG geometry/transparency and every ICO frame. Provider and
  Usage identities now reuse TheSVG's per-brand offline marks alongside the
  existing complete connector catalog.
- Native close verification: the Electron root stayed alive and renderer count
  changed from two to one (Island only), with no rejected polling promises.
- 2026-08-24 resilience repair: focused Gateway tests cover approve, deny,
  expiry, YOLO transition, and token invalidation; focused desktop tests cover
  authoritative-null reconciliation, offline cleanup, confirmation priority,
  pending-button locking, and idle collapse. Desktop typecheck passed.
