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

## Window model

Marvi OS has three surfaces:

1. **Dynamic Island** — always-on-top primary interaction.
2. **Main control center** — settings, state, integrations, and audit.
3. **Tray menu** — open, mute/pause sensors, YOLO state, restart Gateway, exit.

Closing the control center hides it. It does not terminate the Island or local
services.

## Dynamic Island

The Island is smaller than Marvi's previous implementation and grows only for
content that requires attention.

Target sizes at 100% scaling:

| State | Size | Content |
|---|---:|---|
| sleep | `150×30` | minimal glyph and presence dot |
| listening | `210×38` | `LISTEN`, compact live waveform |
| thinking | `230×40` | `THINK`, low-cost ASCII pulse |
| speaking | `250×42` | `SPEAK`, output waveform, interrupt hint |
| action | `280×46` | tool glyph, short verb, progress |
| notification | up to `320×64` | one concise world/room event |
| confirmation | up to `360×92` | exact action summary, approve/deny |

Rules:

- Return to compact state automatically after terminal events.
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
