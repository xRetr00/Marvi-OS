# Hermes Desktop v0.21.0 browser review

Reviewed 2026-09-08 at tag `v2026.8.31`, commit
`29112bef099274229cadff79cdff7bf7b99c4b77`. This is a source review, not a
claim that Hermes was installed or tested on Windows.

## Finding and correction

Hermes v0.21.0 lets its agent operate the browser embedded in the desktop app.
Marvi's Phase 14 selected a separate headed Chromium process and implemented
a control page for it. That provides shared visibility and saved profiles,
but does not provide an in-app browser. This was a product-scope miss, not an
Electron limitation. The user's 2026-09-08 correction makes an embedded,
agent-controlled browser part of delivery acceptance.

## Verified upstream implementation

- [Release notes](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.31)
  identify agent control of the desktop browser: navigation, clicks, reading,
  and pop-out behavior.
- [Preview pane](https://github.com/NousResearch/hermes-agent/blob/29112bef099274229cadff79cdff7bf7b99c4b77/apps/desktop/src/app/chat/right-rail/preview-pane.tsx)
  creates an Electron `webview` with partition `persist:hermes-preview`,
  context isolation, no Node integration, and sandboxing. It registers page
  reading, input, navigation, and script handlers for the live guest.
- [Desktop bridge](https://github.com/NousResearch/hermes-agent/blob/29112bef099274229cadff79cdff7bf7b99c4b77/apps/desktop/src/app/session/hooks/use-message-stream/gateway-event/desktop-bridge.ts)
  handles correlated `preview.read.request` and `preview.act.request` events
  and returns responses. Actions are gated to the active event/session.
- [Input driver](https://github.com/NousResearch/hermes-agent/blob/29112bef099274229cadff79cdff7bf7b99c4b77/apps/desktop/src/app/chat/right-rail/preview-drive.ts)
  sends Chromium input events for pointer, keyboard, and scrolling.
- The pane also registers script execution and reads body `innerText`. Those
  mechanisms alone do not prove a private-login exclusion boundary. This
  review does not claim every Hermes capture/logging path was audited.
- The inspected pane shares one persistent preview partition. This proves
  storage configuration, not named-profile isolation or universal persistence
  of website authentication after restart.

## Marvi implementation boundary

Use the already pinned Electron dependency unchanged. Prefer main-owned
[WebContentsView](https://www.electronjs.org/docs/latest/api/web-contents-view)
over copying Hermes's renderer-owned webview bridge. Electron's
[webview documentation](https://www.electronjs.org/docs/latest/api/webview-tag)
recommends considering alternatives including WebContentsView. No Hermes
implementation code is copied or vendored.

Electron main will own guest lifecycle, persistent sessions, native input,
permissions, download events, and placement. The renderer will submit bounded
placement and user controls, without generic script/debugger capabilities.
Gateway will retain session/tab IDs, revisions, action receipts, confirmations,
audit redaction, and private-input admission. User and agent must operate the
same guest, not independent browsers pointed at the same URL.

The existing Playwright context cannot simply be inserted into a
WebContentsView. An Electron guest is a different browser host. Do not enable
an unauthenticated app-wide remote-debugging port to attach the existing
driver: it also exposes privileged application targets. First prove a narrowly
scoped main/Gateway host adapter across the real process boundary. Keep the
native backend as an explicit qualification fallback, never a silent mid-task
substitution. Driver selection must follow the repository's upstream-first
rule; avoid recreating locator/actionability logic merely to embed the view.

Use a separate storage namespace for Electron's
[persistent sessions](https://www.electronjs.org/docs/latest/api/session).
Do not point Electron at the live Playwright user-data directory or copy cookies.
Existing native profiles remain available in the fallback until migration is
qualified. Website authentication may expire independently of saved storage.

## Revised delivery gates

1. A main-owned sandboxed guest renders inside Browser and survives navigating
   away from that page. Window reopen and Gateway reconnect preserve ownership.
2. Agent read/click/fill/navigation target that exact guest through Gateway
   session/tab identity. Test stale targets, real input, and cross-origin frames.
3. Preserve network admission and isolate privileged app pages/Gateway. Test
   redirects, popups, custom schemes, permissions, certificate errors, downloads,
   and guest crashes.
4. Private input drains admitted actions/captures before acknowledgment. User
   input stays in the guest; all readers and diagnostic streams respect the
   barrier. Resume observes fresh state after user navigation.
5. Prove named-profile isolation and restart persistence. Repeat OBS login and
   the public attachment test on the embedded host; native results do not qualify it.
6. Verify bounds, resize/DPI, tabs, focus, Island priority, hidden-window behavior,
   shutdown, secret canaries, upgrade/recovery, and mixed voice/browser soak.

Status: embedded host is required and not implemented yet. The native workspace
remains under qualification. Computer-use planning remains separate.
