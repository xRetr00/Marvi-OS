# UI Contract

## Visual identity

Marvi OS uses a modern monochrome ASCII system inspired by the repository and
icon artwork without displaying the repository banner in the application.

Palette:

| Token | Value | Use |
|---|---:|---|
| `void` | `#050505` | primary background |
| `obsidian` | `#0A0A0B` | raised surfaces |
| `graphite` | `#17181A` | borders and separators |
| `ash` | `#72767D` | secondary labels |
| `bone` | `#E7E7E3` | primary text/glyphs |
| `white` | `#FAFAF8` | active highlights |
| `signal` | `#147EC1` | restrained status accent from the icon |
| `danger` | `#D85B5B` | destructive/error only |

Blue is a status signal, not a general decorative gradient. Avoid colorful
cards. Use monospaced typography, ASCII separators, compact uppercase labels,
and crisp one-pixel geometry. Do not add scanlines, blur, chromatic aberration,
or noise that reduces legibility.

## Application icon and repository artwork

- `assets/app-icon-source.png` is the source for ICO/PNG packaging outputs.
- `assets/marvi-os-banner.png` is README/repository artwork only.
- Never show or package the repository banner in the main window, About, splash,
  onboarding, tray, Dynamic Island, installer, or notifications.
- The app icon appears in the Windows executable/taskbar, tray, sidebar brand,
  and About view. Generate purpose-sized assets from the canonical source;
  never ask Windows to downsample the 1254 px source at runtime.

## Window model

Marvi OS has three surfaces:

1. **Dynamic Island** — always-on-top primary interaction.
2. **Main control center** — settings, state, integrations, and audit.
3. **Tray menu** — open, mute/pause sensors, YOLO state, restart Gateway, exit.

Closing the control center hides it. It does not terminate the Island or local
services.

## Frameless shell and custom title bar

The control center is frameless (`frame: false`, `titleBarStyle: 'hidden'`).
The native Windows title bar never renders; the shell paints its own 40 px
title bar: brand mark, current page, and minimize / maximize / close controls.
The bar is the window drag region; interactive children opt out of drag.
Double-click on the bar toggles maximize, matching Windows shell behavior.
Close hides to tray per the always-on contract; quit stays on the tray menu.

The shell adds the Hermes-derived chrome pieces, adapted to the Marvi OS
contract: a glyph spinner (`unicode-animations`), a decode-text CONNECTING
overlay for initial boot, a boot-failure recovery overlay with diagnostics and
retry, web haptics on taps/selections/confirmations, a shell context menu on
right-click of chrome, a translucency lever (0–100 → native window opacity,
floor 0.3), and the Electric Gaze animated ASCII backdrop. The backdrop is a
vendored local asset (`apps/desktop/src/renderer/src/assets/background/`),
never fetched at runtime. Backdrop opacity and translucency are persisted
per-machine. Reduced-motion users get static text and no exit choreography.

The status bar keeps the persistent readouts and adds a live voice-level
meter (8 ASCII cells) so the shell reads "alive" at a glance.

## Dynamic Island

The Island is smaller than Marvi's previous implementation and grows only for
content that requires attention.

Target sizes at 100% scaling:

| State | Size | Content |
|---|---:|---|
| sleep | `76×8` | recessed top-edge seed; only a short light line remains visible |
| listening | `210×38` | `LISTEN`, compact live waveform |
| thinking | `230×40` | `THINK`, low-cost ASCII pulse |
| speaking | `250×42` | `SPEAK`, output waveform, interrupt hint |
| action | `280×46` | tool glyph, short verb, progress |
| notification | up to `320×64` | one concise world/room event |
| confirmation | up to `360×92` | exact action summary, approve/deny |

Rules:

- Return to compact state automatically after terminal events.
- In passive sleep, remove the seed body completely and leave only its short
  light line at the work-area edge. Do not leave the ready pill, label, or
  waveform visible until wake/activity begins.
- Never show a full transcript.
- Never animate merely to hide latency.
- Coalesce audio-level rendering to a bounded frame rate.
- Spoken approval and pointer approval resolve the same Gateway token.
- YOLO mode shows a persistent lightning glyph and `YOLO` marker even asleep.
- Camera/microphone local activity uses tiny state glyphs, not large banners.
- Background events may animate the Island but may not focus the main window.
- The native host follows measured content plus a small transparent shadow
  inset. Resize only at content/state boundaries; never animate native window
  bounds per frame.
- Passive states are click-through, non-focusable, non-movable, frameless, and
  have no host background. Pointer/focus is enabled only for temporary actions.

Typography reuses the current Marvi desktop faces: Collapse for the product
wordmark and JetBrains Mono for ASCII construction, labels, status, and data.

## Main control center

The main window uses a fixed shell:

```text
┌ MARVI OS ────────────────────────────────────────────────────────────────┐
│ SIDEBAR        │ CURRENT VIEW                                           │
│                │                                                        │
│ Overview       │                                                        │
│ Activity       │                                                        │
│ World          │                                                        │
│ Room           │                                                        │
│ Memory         │                                                        │
│ Integrations   │                                                        │
│ Voice & Vision │                                                        │
│ Settings       │                                                        │
│ Updates        │                                                        │
│ About          │                                                        │
├────────────────┴────────────────────────────────────────────────────────┤
│ ● GATEWAY  ● VOICE  ● VISION  ● ROOM   MODEL   MODE   v0.1.0          │
└─────────────────────────────────────────────────────────────────────────┘
```

The sidebar is navigation, not a second dashboard. The bottom status bar is
always present and shows compact authoritative health:

- Marvi Gateway
- LiveKit transport
- STT/TTS readiness
- microphone/camera state
- Smart Room connection/presence
- OpenCode Go model
- Confirm or YOLO mode
- version/update indicator

Status items open the relevant view; they do not create nested popovers with
duplicated settings.

## Island micro-events

Background room events ride a channel of their own on the assistant state, not
the voice `phase`. A room event therefore cannot overwrite a live voice turn or
a pending confirmation — a live phase and a confirmation both outrank it.

A micro-event expands the seed into a two-column pill for a few seconds and
collapses on its own. It carries no controls, never becomes interactive, and is
announced politely rather than assertively, so it cannot pull focus. The
persistent YOLO marker stays visible while one is showing.

Only meaningful transitions qualify. Ambient sensor churn and bursty detections
are filtered out at the Gateway, and event text is rebuilt from the event
payload so a line always names what actually changed. A backlog that already
existed when Marvi started is never surfaced as a micro-event.

## Room and Activity views

Room shows the sidecar connection state and the live room reading: mode, light,
presence, and phone location. When the sidecar is unreachable the view keeps
serving its last known state and says so explicitly rather than showing an empty
or stale-looking panel. It also lists recent notable room events, newest first.
Room is read-only; device authority stays in the sidecar.

Activity is the append-only local tool audit, newest first. Each row shows the
tool, the lifecycle event, the time, the active mode, and the exact arguments.
YOLO executions appear identically to confirmed ones — the mode is a column, not
a reason to hide a record. Nothing on this view is sent anywhere.

## Accounts and Memory views

Accounts lists every connected toolkit and its state. Marvi OS never collects a
provider password and never runs an OAuth flow — Composio owns the connections,
and a dead one says plainly that it must be reconnected there.

Memory shows what is stored, how much, and where each entry came from. An entry
that originated outside the machine is labelled untrusted rather than shown as
an ordinary fact. Deleting everything is a two-step action, never a single
click, and export returns the user's own data verbatim.

## About view

About uses the app icon, not the repository banner. It contains:

- product name and product version;
- Git commit, build time, architecture, and update channel;
- Marvi Gateway and LiveKit versions;
- selected STT/TTS model and revision;
- upstream license/provenance link;
- Check for Updates and diagnostics export actions.

The sidebar and status bar remain visible in About.

## Settings behavior

Settings include:

- startup and Island placement;
- microphone, camera, wake word, presence, and gesture controls;
- voice models and residency profile;
- OpenCode Go key/model selection;
- Composio connections;
- Smart Room endpoint;
- memory policy;
- Confirm/YOLO mode;
- update channel and update checks;
- privacy and audit retention.

Enabling YOLO requires an explicit settings action and immediately updates the
Island and status bar. The product does not add per-action confirmations while
YOLO is active.
