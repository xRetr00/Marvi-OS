# Phase 2 — Desktop Shell and Dynamic Island

**Status:** in progress
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
- Canonical icon used in the sidebar and About, with generated 16–256 px ICO
  entries, 32 px tray PNG, 256 px runtime/renderer PNG, and 512 px package PNG.
- About surface exposes version, commit, build time, target architecture,
  update channel, and current Gateway/LiveKit/voice component status.

## Design-source review

- `D:\hermes-agent\apps\desktop\DESIGN.md`
- `D:\hermes-agent\apps\desktop\src\styles.css`
- `D:\hermes-agent\apps\desktop\src\app\voice-island`
- `D:\hermes-agent\apps\desktop\electron\main.ts`

The old Marvi Island deliberately uses a fixed transparent stage to avoid
Windows resize animation jank. Marvi OS instead resizes only when content
dimensions change at state boundaries; CSS does not tween the Island's geometry.
This satisfies content-sized native bounds without resizing every animation
frame.

## Remaining

- Add action, notification, confirmation, YOLO, device-state, and error views.
- Enable pointer/focus only while an actionable confirmation is visible.
- Connect authoritative Gateway health instead of scaffold labels.
- Complete About metadata, Settings, Updates, accessibility, multi-monitor
  placement, display-scale, idle-cost, and visual-regression checks.

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
