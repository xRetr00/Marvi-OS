# Phase 12 — measured desktop pet companion

Status: **in progress** — native-helper spike complete; product keep/draft
decision and 60-minute soak pending.

## Outcome

Marvi OS can show the supplied character as an optional draggable desktop
companion without changing Gateway, voice, tool, or confirmation authority.

The original Electron pet renderer proved behavior but cost 70.08 MiB of
incremental private memory. The spike replaces that third Chromium surface with
a focused Windows helper while preserving the existing atlas, phase mapping,
frame timings, gaze mapping, placement, and true-off behavior.

## Implemented boundary

- The owned 1536×2288 WebP atlas remains unchanged: 8 columns × 11 rows,
  `192×208` cells, 2,159,684 bytes.
- `apps/pet-host` is a 388,608-byte Rust/Win32 executable. It decodes WebP with
  `image`, caches only rendered scale/frame combinations, and presents them
  through a transparent layered GDI window.
- Electron main supervises the helper and sends only bounded newline-delimited
  JSON commands: assistant phase/count, 16-way gaze index, hover, bounds, and
  exit. The helper emits only `voice` and `tasks` button intents plus a final
  drag position for Electron to validate and persist.
- The helper has no Gateway, LiveKit, microphone, camera, tool, network, tray,
  settings, or durable-state access.
- Authored one-shot frame durations are identical to the v2 pet contract.
  Windows' client-area-animation preference freezes state loops while retaining
  direct gaze updates.
- Fresh installs default to a 50% `96×104` sprite to match the supplied Codex
  reference. A scaled 32 px transparent strip beneath it holds the status and
  hover controls, making the default native host `96×136`. Settings expose
  40%, 50%, 70%, and 100% without modifying or resampling the packaged atlas
  ahead of time.
- The status line is gray when idle, blue while working, green for notification
  or a two-second active-to-ready completion, and red on error. Hover reveals
  refined Voice and current-operation controls. Visible pet/status pixels
  accept pointer input and form the native drag surface; transparent gaps stay
  click-through. Voice opens Voice and Tasks opens the existing Activity audit
  through Electron main.
- Electron clamps the completed drag to the selected monitor and saves it.
  Changing display, side, or scale resets to the chosen corner. The pet can be
  hidden or restored from either Settings or the tray; hiding terminates the
  helper.
- Disabling the pet terminates the helper. Unexpected termination leaves Marvi
  alive and restarts only the helper after one second.

## Verification

- `cargo test --manifest-path apps/pet-host/Cargo.toml`: exact phase rows,
  authored durations/wrap, and both gaze rows pass.
- `cargo clippy --manifest-path apps/pet-host/Cargo.toml --all-targets -- -D warnings`
  and `cargo fmt --check` pass.
- Desktop unit tests cover preference/drag normalization, clamped custom and
  50% bounds, sprite/control geometry, gaze quantization, helper event
  validation, active count, action routing, and the native protocol/path
  contract. Rust tests cover compact button geometry and alpha-aware hit
  testing that captures rendered pixels without blocking transparent gaps.
- `npm run build:unpack` packages `marvi-pet-host.exe` and the atlas under
  `resources/pet-host/`; the renderer bundle no longer contains the atlas.
- `scripts/capture-native-pet.ps1` captures both the packaged indicator and the
  hover-revealed controls without focusing Marvi. Evidence:
  `output/evidence/pet-native-status-idle.png` and
  `output/evidence/pet-native-controls-hover.png` (ignored by Git). The
  unreachable test Gateway correctly produced the red error indicator.
- `scripts/test-native-pet-restart.ps1` forcibly terminates the packaged helper,
  verifies Marvi remains alive, and observes a replacement helper PID. Evidence:
  `output/evidence/pet-native-restart.json` (ignored by Git).
- `scripts/test-native-pet-controls.ps1` hides the packaged control center,
  sends a Tasks click through the real native window and stdout bridge, and
  verifies Electron reveals the `Marvi OS` window. Evidence:
  `output/evidence/pet-native-controls.json` (ignored by Git).
- `scripts/measure-desktop-pet.ps1 -WarmupSeconds 12 -SampleSeconds 12` measures
  every Marvi descendant and reports the helper separately. Evidence:
  `output/evidence/pet-resource-measurement.json` (ignored by Git).

## Native resource evidence

Host: Windows 11 Pro, AMD Ryzen 5 3600X, 15.9 GiB RAM, Electron 43.4.0,
Marvi OS 0.4.15 win-unpacked. Voice management was disabled and Gateway used an
unreachable loopback address in both modes.

| Direct helper metric      |                                Result |
| ------------------------- | ------------------------------------: |
| Added processes           | 1 native helper; 0 Chromium renderers |
| Average working set       |                             23.62 MiB |
| Average private bytes     |                             16.44 MiB |
| CPU over 12-second sample |                     0.00% of one core |
| Executable size           |                              0.37 MiB |

The direct helper measurement remained stable in the packaged run. This
passes the spike's ≤25 MiB private-memory and ≤0.5%-of-one-core targets and is a
76.5% reduction from the prior renderer's 70.08 MiB private cost.

The latest paired whole-app deltas were +183.24 MiB working set and +59.26 MiB
private. Earlier paired runs varied widely and even changed sign while direct
helper measurements stayed stable, locating the swing in the existing Electron
renderers rather than this helper. Whole-app deltas are therefore retained as
noisy evidence, not attributed to the helper.

## Decision gate

The spike is technically successful but remains experimental. Before shipping:

1. run a 60-minute idle/state-transition soak with the managed voice stack;
2. verify per-monitor DPI and display hot-plug on the target display set;
3. decide whether the simple layered-GDI presenter is sufficient or should be
   replaced by a Direct2D surface without changing the protocol;
4. have the product owner choose **Keep** or **Draft** for this branch.
