# UI Contract

## Visual identity

Marvi OS uses a modern monochrome ASCII system inspired by the repository and
icon artwork without displaying the repository banner in the application.

Palette:

| Token      |     Value | Use                                    |
| ---------- | --------: | -------------------------------------- |
| `void`     | `#050505` | primary background                     |
| `obsidian` | `#0A0A0B` | raised surfaces                        |
| `graphite` | `#17181A` | borders and separators                 |
| `ash`      | `#72767D` | secondary labels                       |
| `bone`     | `#E7E7E3` | primary text/glyphs                    |
| `white`    | `#FAFAF8` | active highlights                      |
| `signal`   | `#147EC1` | restrained status accent from the icon |
| `danger`   | `#D85B5B` | destructive/error only                 |

Blue is a status signal, not a general decorative gradient. Avoid colorful
cards. Use monospaced typography, ASCII separators, compact uppercase labels,
thin abstract line icons, and crisp one-pixel geometry. Collapse is reserved
for the product wordmark; headings, prose, controls, and data use JetBrains
Mono with readable size, weight, line height, and tracking. Do not add
scanlines, blur, chromatic aberration, or noise that reduces legibility.

## Application icon and repository artwork

- `assets/app-icon-source.png` is the source for ICO/PNG packaging outputs.
- `assets/marvi-os-banner.png` is README/repository artwork only.
- Never show or package the repository banner in the main window, About, splash,
  onboarding, tray, Dynamic Island, installer, or notifications.
- The app icon appears in the Windows executable/taskbar, tray, sidebar brand,
  and About view. Generate purpose-sized assets from the canonical source;
  never ask Windows to downsample the 1254 px source at runtime.

## Bootstrap window

The installer/updater uses the same monochrome tokens, compact uppercase labels,
monospaced data, crisp borders, and restrained status color as the desktop. Its
long-running log remains selectable. Terminal failures show recovery guidance
and a clear keyboard-accessible Close updater action; they never disappear on a
timer. Only a verified successful result closes the window automatically after
a brief completion state.

## Window model

Marvi OS has four surfaces:

1. **Dynamic Island** — always-on-top primary interaction.
2. **Desktop pet** — optional companion presentation with two bounded controls.
3. **Main control center** — settings, state, integrations, and audit.
4. **Tray menu** — open, mute/pause sensors, YOLO state, restart Gateway, exit.

Closing the control center hides it. It does not terminate the Island or local
services.

## Desktop pet

The pet is an experimental presentation of the same Gateway-authoritative
assistant state used by the Island. It is not a second agent, cannot execute
tools, never reads the Codex user-data directory, and has no independent
conversation state.

- Electron main owns native-helper lifecycle, monitor/cursor access, validated
  placement persistence, and the tray visibility command.
- The native helper owns only a transparent, frameless, non-focusable,
  always-on-top layered window. It crops the packaged 8×11 WebP
  atlas and selects animation rows from the phase received over stdin.
- Ready, listening, and speaking may use one of 16 quantized cursor-gaze frames.
  Cursor coordinates never cross into Gateway or durable storage.
- Wake waves; thinking runs; speaking reviews; actions run; notifications jump;
  confirmations wait; errors use the failed loop; passive states idle.
- Reduced-motion preference freezes the representative first frame.
- Preferences expose visible/hidden, display, left/right corner, and
  40%/50%/70%/100% size. Fresh installs default to the Codex-like 50% size.
  The tray also exposes Show/Hide Desktop Pet, so a hidden pet can be restored
  without opening Settings. Hidden terminates the helper, so disabled means no
  pet process.
- A short line below the sprite communicates authoritative state: gray when
  idle, blue while working, green for completion, and red on error. Completion
  is a two-second presentation transition after active work returns to ready;
  it does not create a second runtime phase.
- Hovering the pet or its reserved transparent control strip reveals two
  compact outlined buttons with a balanced waveform and a crisp task count/list
  glyph. Voice opens the existing Voice view; Tasks opens the
  existing Activity audit because Marvi has no separate task subsystem yet.
  The count is `1` only while the single authoritative operation is thinking,
  acting, or awaiting confirmation, and `0` is shown as a compact chevron.
- The helper remains non-focusable. Visible pet and status pixels capture the
  pointer and form a native drag surface; transparent pixels outside the
  rendered silhouette and controls remain click-through. Electron validates,
  clamps, and persists the final drag position. Button actions travel to
  Electron main, which alone may reveal and navigate the control center.
  Confirmation remains on the Dynamic Island; the pet never becomes a
  confirmation or tool-execution authority surface.
- The source artwork is repository-owned input and the generated atlas is
  packaged locally. No runtime image generation or remote fetch occurs.

The resource cost is intentionally a product gate, not an unmeasured promise.
Current native measurements and the keep/draft decision are tracked in
`docs/phases/12-pet-companion.md`.

## Hidden title bar and native window controls

The control center uses Electron's hidden-titlebar overlay. The renderer paints
the 34 px drag surface and page title; Windows paints minimize, maximize, and
close at the right edge. Renderer actions use 24 px hit targets and 13.9 px
Lucide glyphs, matching the pinned upstream shell. Interactive children opt out
of the drag region. Close still hides to tray per the always-on contract; quit
stays on the tray menu.

The shell adds the the predecessor assistant-derived chrome pieces, adapted to the Marvi OS
contract: a glyph spinner (`unicode-animations`), a decode-text CONNECTING
overlay for initial boot, a boot-failure recovery overlay with diagnostics and
retry, web haptics on taps/selections/confirmations, a shell context menu on
right-click of chrome, a translucency lever (0–100 → native window opacity,
floor 0.3), and the Electric Gaze animated ASCII backdrop. The backdrop is a
vendored local asset (`apps/desktop/src/renderer/src/assets/background/`),
never fetched at runtime. Backdrop opacity and translucency are persisted
per-machine. Reduced-motion users get static text and no exit choreography.

The shell uses compact desktop chrome: a 34 px hidden titlebar lets Electron
paint native Windows controls into the right edge. A single 20 px status bar
occupies the bottom shell track across the full window, including beneath the
active sidebar, and splits icon-led actions into left and right groups. Status
actions use compact labels, detail text, hover transitions, and Lucide glyphs.
The restrained blue eight-cell live voice meter is intentionally retained from
Marvi's earlier voice design. Its version action opens build/update details
without navigating away from the current task.

## ARC memory graph

The Memory page is ARC's inspection surface. Its graph keeps the interaction
model of the pinned OpenHuman reference: node/link counts, an inline legend,
tree/connection modes, reset-view control, pan, cursor-anchored zoom, draggable
nodes that pull their linked neighbours, and a hover inspector. The production
renderer uses PixiJS WebGL with d3-force physics, following the pinned MIT
Advanced Graph View architecture rather than the earlier static radial SVG.
OpenHuman remains a reference only because it is GPL-3.0 and Marvi OS is MIT.

The graph remains inside the control-center shell and uses Marvi's monochrome
tokens with blue only for the ARC root/status signal and red only for untrusted
provenance. It never imports the reference's colorful palette, rounded app
chrome, or renderer-side data ownership. Tree mode groups entries below their
source; Connections mode renders only Gateway-authoritative entity relations.
An empty graph explains how it will fill instead of showing a dead canvas.
Reduced-motion mode settles the simulation immediately instead of leaving the
graph in continuous motion.

## Dynamic Island

The Island is smaller than Marvi's previous implementation and grows only for
content that requires attention.

Target sizes at 100% scaling:

| State        |           Size | Content                                                         |
| ------------ | -------------: | --------------------------------------------------------------- |
| sleep        |         `76×8` | recessed top-edge seed; only a short light line remains visible |
| listening    |       `210×38` | `LISTEN`, compact live waveform                                 |
| thinking     |       `230×40` | `THINK`, low-cost ASCII pulse                                   |
| speaking     |       `250×42` | `SPEAK`, output waveform, interrupt hint                        |
| action       |       `280×46` | tool glyph, short verb, progress                                |
| notification | up to `320×64` | one concise world/room event                                    |
| confirmation | up to `360×92` | exact action summary, approve/deny                              |

Rules:

- Return to compact state automatically after terminal events.
- Approval, denial, expiry, and mode-change results remain visible for three
  seconds, then return to the passive state. A Gateway outage removes stale
  confirmation controls immediately and shows the non-interactive error state.
- In passive sleep, remove the seed body completely and leave only its short
  light line at the work-area edge. Do not leave the ready pill, label, or
  waveform visible until wake/activity begins.
- Never show a full transcript.
- Never animate merely to hide latency.
- Coalesce audio-level rendering to a bounded frame rate.
- Spoken approval and pointer approval resolve the same Gateway token.
- YOLO mode never changes Island presentation. Its persistent warning remains
  in the control-center status bar and tray; enabling it burns any
  already-issued Confirm-mode tokens without executing their actions.
- Camera, microphone, and global mode indicators do not appear in the Island.
  Their authoritative state remains available in the control center.
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
│ ◇ Overview     │                                                        │
│ ◉ Voice        │                                                        │
│ ⌁ Chat         │                                                        │
│ ⬡ Vision       │                                                        │
│ ⌂ Room         │                                                        │
│ ≋ Activity     │                                                        │
│ ...            │                                                        │
├────────────────┴────────────────────────────────────────────────────────┤
│ ● GATEWAY  ● VOICE  ● VISION  ● ROOM   MODEL   MODE   v0.1.0          │
└─────────────────────────────────────────────────────────────────────────┘
```

The sidebar is navigation, not a second dashboard. Every destination uses a
purpose-built abstract line icon, a plain label, and a short code. The expanded
rail includes a compact brand descriptor; the collapsed rail keeps the icons
and active indicator legible, and keeps the canonical Marvi mark in its brand
cell so the compact rail never becomes anonymous. Collapse uses a narrow panel
glyph rail control, not bracket text. Chromium View Transitions move the sidebar and content as
compositor snapshots; reduced-motion users get an immediate state change. The
bottom status bar is always present and shows compact authoritative health:

- Marvi Gateway
- LiveKit transport
- STT/TTS readiness
- microphone/camera state
- Smart Room connection/presence
- OpenCode Go model
- Confirm or YOLO mode
- version/update indicator

Health items open the relevant view. The version item is the sole exception:
it opens a compact popover with version, channel, commit, build time, last
update result, and check/update actions. Full update controls live in About;
there is no separate Updates settings destination.

Chat and Voice show the same session timing strip. Usage is the sole source of
truth for durable provider and session counters; Providers only configures
connections. The displayed session token count is the delta from the first
Gateway usage snapshot after this renderer session starts, so
it accumulates across chat and voice turns without inventing token estimates.
Chat latency measures request-to-reply time; voice latency measures the active
listen/wake-to-speaking transition. Turn and duration counters continue while
the renderer session remains open.

The Chat composer keeps its native Marvi controls and Gateway-backed turn
behavior inside a rounded Assistant UI-style paper surface. Focus and streaming
state use a restrained static blue edge; the input does not run a decorative
border animation.

The rest of Chat adapts Assistant UI's thread composition without adopting a
second runtime. Entering Chat replaces the control-center navigation with a
dedicated conversation sidebar adapted from the pinned upstream desktop.
That sidebar owns new-chat, search, recent threads, row actions, export, and a
clear return to the control center. Chat has no secondary page header. A compact
560px reading column owns message flow; each turn follows the compact upstream
human/assistant pair: one slim full-width prompt surface followed by unboxed
Marvi prose. Sender labels remain available to assistive technology instead of
repeating as visible headers, while timestamps and actions appear on hover or
keyboard focus. The composer uses the same 560px register with 24px controls.
Durable threads and branches back the sidebar, edit, and regenerate actions.
GitHub-flavored Markdown, math, tables, code blocks, source rows, image/file
parts, read aloud, local-native dictation, model selection, and context details
use distinct bounded modules instead of one undifferentiated text column.
Tool activity and sources use transparent faded disclosure
rows at rest, a small `Sources · count` label, and compact flat result rows only
after expansion. Structured results use thin dividers instead of nested paper
cards, with progressive disclosure and no model-authored UI code. Context
percentage is shown only when both provider input usage and a catalog context
window are known.
Message actions appear on hover or keyboard focus, reasoning and tool evidence
stay collapsed, the composer remains docked, and leaving the latest scroll
position reveals a return-to-latest control. Dynamic follow-up suggestions are
not part of the product. See `docs/CHAT.md` for the authority and safety
boundaries.

Overview and every secondary control-center page share one compact desktop
grammar: a quiet page heading, small icon-led section headings, flat divided
rows, restrained status pills, and 28 px actions. Configuration pages may use
pickers or editors inside those sections, but never loose status prose, noisy
ASCII framing, or a grid of decorative cards. Content is capped at 880 px so
labels and values remain easy to scan. Narrow windows stack row actions below
their labels. Voice and Chat retain their purpose-built interaction layouts.

Settings opens as one inset dialog with a 208 px navigation
rail and the same content grammar. The flat rail uses sentence-case 28 px rows,
separates related destinations with whitespace instead of printed group labels,
and leaves the compact close button floating at the dialog's top-right. Each
setting is a container-responsive label/description/action row; controls align
in one right column and stack below their copy only when the content pane is
narrow. The rail becomes a two-column strip before stacking above content on
small windows. The general navigation rail is 212 px expanded and 52 px
collapsed; the app logo stays visible in the collapsed rail and the title bar
owns the collapse action.

Settings destinations follow the Models page's one-purpose page structure:
one quiet page heading, one or more icon-led sections, then flat setting rows.
Voice expands to three purpose-built child pages: **Speech recognition** (STT),
**Wake word**, and **Voice synthesis** (TTS), so opening a destination answers
one question without crowding the top-level rail. Window, backdrop, Island, and
desktop-companion presentation live under **Appearance**; runtime, approval
mode, and device health remain under **Preferences**.

Async page work uses the shared Processing Card. It shows a real percentage
only when the underlying operation reports one; otherwise the scan and moving
bar are explicitly indeterminate. The visual is adapted from the supplied
reference into Marvi's monochrome/blue vocabulary, contains no external brand,
and never advances a fake random counter. Usage adapts the supplied calendar
concept into UTC daily token buckets without its external GitHub fetch or game
mode.

Icon-only and ambiguous shell controls use the shared accessible tooltip
surface. Tooltips appear on hover and keyboard focus after a short delay, use
the same one-pixel geometry as the shell, and never replace an accessible name.
The title bar, compact navigation rail, and settings close control use one
matching abstract SVG language; platform-symbol text glyphs are not used.

Desktop haptics use `web-haptics` with its documented debug audio-transducer
path enabled. Electron on Windows does not expose the mobile Vibration API, so
disabling that path makes otherwise valid triggers silent. Haptic failures are
non-blocking and never interrupt the action that requested feedback.

## Island micro-events

Background room events ride a channel of their own on the assistant state, not
the voice `phase`. A room event therefore cannot overwrite a live voice turn or
a pending confirmation — a live phase and a confirmation both outrank it.

A micro-event expands the seed into a two-column pill for a few seconds and
collapses on its own. It carries no controls, never becomes interactive, and is
announced politely rather than assertively, so it cannot pull focus. The
event label describes only the event; global mode and sensor status stay out of
the Island.

Only meaningful transitions qualify. Ambient sensor churn and bursty detections
are filtered out at the Gateway, and event text is rebuilt from the event
payload so a line always names what actually changed. A backlog that already
existed when Marvi started is never surfaced as a micro-event.

## Vision, Room, and Activity views

Vision and Room follow the smart room information order while
remaining separate Marvi control-center destinations. Both start with a compact
authoritative runtime header and one bounded live workspace before falling back
to flat divided operational sections. Their workspaces use container queries to
stack at the content boundary rather than a fixed window breakpoint.

Room shows mode, light, presence, and phone location beside the existing
Gateway-backed light, brightness, and mode controls. Controls invoke the same
audited tools and local-action policy as voice requests; device authority and
credentials remain in the sidecar. Device and MQTT health follow the live
workspace, then recent notable room events appear newest first. When the sidecar
is unreachable, the view preserves its last known state and labels it stale.

Vision owns presentation of camera state, identity review, and vision-specific
history. The Smart Room sidecar remains the sole camera and inference owner.
While the Vision page is mounted, the renderer requests one bounded 720 px JPEG
preview every 500 ms through Gateway and Electron; frames are not queued,
persisted, or fetched in the background. Derived presence, identity, sleep,
activity, and gesture state remains separate from that presentation frame.
Owner enrollment and pending face decisions use the same preview-led flow as
that desktop and still travel through the normal Gateway tool boundary.

Room's light editor follows that desktop's complete control flow: current power and
brightness, on/off, a continuous brightness range, white temperature, custom
RGB and preset swatches, then all eight room modes. RGB is functional device
color rather than a decorative UI palette. Controls stay disabled until the
Gateway has a live confirmed room state, and sliders apply on release.

Activity is the append-only local tool audit, newest first. Each row shows the
tool, the lifecycle event, the time, the active mode, and the exact arguments.
YOLO executions appear identically to confirmed ones — the mode is a column, not
a reason to hide a record. Nothing on this view is sent anywhere.

## Accounts and Memory views

Accounts owns the visible Composio lifecycle. It lists every connection rather
than collapsing multiple accounts, opens Composio's hosted Connect Link in the
system browser, and provides reconnect, enable/disable, two-step revoke, and
manual sync actions. Marvi never renders the provider login or receives its
credential.

On first use, Accounts accepts the Composio project API key in a masked field.
Gateway validates it before saving it through the existing local secret-setting
path; the key is never echoed back to the renderer. A successful save activates
the catalog and realtime listener immediately.

Every account starts with a read-only capability ceiling. A compact three-state
strip lets the user choose read, write, or admin; this limits agent discovery
and execution but never bypasses Confirm/YOLO. Native Gmail, Calendar, Slack,
Notion, GitHub, and Drive rows also expose memory auto-fetch and per-connection
last-success/error health. The page identifies whether realtime triggers are
connected or periodic polling is carrying observation.

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
- update channel, check, download/handoff, and last-result controls;
- diagnostics export action.

The sidebar and status bar remain visible in About.

## Settings behavior

Settings include:

- separate Speech recognition (STT), Voice synthesis (TTS), and Wake word pages;
- an Appearance page for the control center, Island, and desktop companion;
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
status bar and tray. It does not keep the idle Island expanded. The product
does not add per-action confirmations while YOLO is active.
