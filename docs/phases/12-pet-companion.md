# Phase 12 — measured desktop pet companion

Status: **in progress** — native-helper spike complete; product keep/draft
decision and 60-minute soak pending.

## Outcome

Marvi OS can show the supplied character as an optional click-through desktop
companion without changing Gateway, voice, tool, or confirmation authority.
The work remains isolated on `codex/pet-support` in
`D:\Marvi-OS-pet-support`.

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
  JSON commands: assistant phase, 16-way gaze index, bounds, and exit.
- The helper has no Gateway, LiveKit, microphone, camera, tool, network, tray,
  settings, or durable-state access.
- Authored one-shot frame durations are identical to the v2 pet contract.
  Windows' client-area-animation preference freezes state loops while retaining
  direct gaze updates.
- Fresh installs default to 50% (`96×104`) to match the supplied Codex
  reference. Settings expose 40%, 50%, 70%, and 100% without modifying or
  resampling the packaged atlas ahead of time.
- Disabling the pet terminates the helper. Unexpected termination leaves Marvi
  alive and restarts only the helper after one second.

## Verification

- `cargo test --manifest-path apps/pet-host/Cargo.toml`: exact phase rows,
  authored durations/wrap, and both gaze rows pass.
- `cargo clippy --manifest-path apps/pet-host/Cargo.toml --all-targets -- -D warnings`
  and `cargo fmt --check` pass.
- Desktop unit tests cover preference normalization, 50% bounds, gaze
  quantization, and the native protocol/path contract.
- `npm run build:unpack` packages `marvi-pet-host.exe` and the atlas under
  `resources/pet-host/`; the renderer bundle no longer contains the atlas.
- `scripts/capture-native-pet.ps1` confirms the packaged 96×104 transparent
  overlay at the bottom-right without focusing Marvi. Evidence:
  `output/evidence/pet-native-helper.png` (ignored by Git).
- `scripts/test-native-pet-restart.ps1` forcibly terminates the packaged helper,
  verifies Marvi remains alive, and observes a replacement helper PID. Evidence:
  `output/evidence/pet-native-restart.json` (ignored by Git).
- `scripts/measure-desktop-pet.ps1 -WarmupSeconds 12 -SampleSeconds 12` measures
  every Marvi descendant and reports the helper separately. Evidence:
  `output/evidence/pet-resource-measurement.json` (ignored by Git).

## Native resource evidence

Host: Windows 11 Pro, AMD Ryzen 5 3600X, 15.9 GiB RAM, Electron 43.4.0,
Marvi OS 0.4.15 win-unpacked. Voice management was disabled and Gateway used an
unreachable loopback address in both modes.

| Direct helper metric | Result |
| --- | ---: |
| Added processes | 1 native helper; 0 Chromium renderers |
| Average working set | 23.50 MiB |
| Average private bytes | 15.64 MiB |
| CPU over 12-second sample | 0.00% of one core |
| Executable size | 0.37 MiB |

The direct helper measurements were identical in repeated packaged runs. This
passes the spike's ≤25 MiB private-memory and ≤0.5%-of-one-core targets and is a
77.7% reduction from the prior renderer's 70.08 MiB private cost.

Paired whole-app working-set deltas were +140.09 MiB and +142.23 MiB, while
paired private deltas changed sign (+13.08 MiB and -10.42 MiB). Per-process
inspection showed the helper itself stable at 23.50 MiB working set / 15.64 MiB
private; the remaining swing came from the already-running Electron renderers.
Whole-app deltas are therefore retained as noisy evidence, not attributed to
the helper.

## Decision gate

The spike is technically successful but remains experimental. Before shipping:

1. run a 60-minute idle/state-transition soak with the managed voice stack;
2. verify per-monitor DPI and display hot-plug on the target display set;
3. decide whether the simple layered-GDI presenter is sufficient or should be
   replaced by a Direct2D surface without changing the protocol;
4. have the product owner choose **Keep** or **Draft** for this branch.
