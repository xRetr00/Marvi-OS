# Phase 12 — measured desktop pet companion

Status: **in progress** — implementation and native evidence complete; product
keep/draft decision pending.

## Outcome

Marvi OS can show the supplied Marvi character as an optional desktop
companion without changing Gateway, voice, tool, or confirmation authority.
The prototype is isolated on `codex/pet-support` in worktree
`D:\Marvi-OS-pet-support` so it can be kept, optimized, or drafted without
touching the active checkout.

## Implemented boundary

- Packaged, local 1536×2288 WebP atlas: 8 columns × 11 rows, `192×208` cells,
  2,159,684 bytes on disk.
- Dedicated transparent Electron BrowserWindow, always-on-top, non-focusable,
  non-movable, and permanently click-through.
- Electron main owns window lifecycle, monitor placement, preference
  persistence, and 10 Hz cursor sampling reduced to a 16-way direction index.
- The React pet surface owns presentation only. It draws at the atlas' native
  cell resolution, advances at authored frame durations, and stops animation
  for reduced-motion users.
- Gateway assistant phases map to idle, wave, run, review, jump, wait, and failed
  loops. Ready/listening/speaking may use the gaze rows.
- Preferences control visible/hidden, monitor, left/right corner, and 75%/100%
  scale. Disabling destroys the BrowserWindow instead of keeping a hidden
  renderer resident.

## Verification

- `npm test`: 30 files, 201 tests passed, including pet placement,
  normalization, gaze quantization, phase mapping, and atlas-row coverage.
- `npm run build`: typechecks main/preload/renderer and emits the atlas into the
  production renderer bundle.
- `npm run build:unpack`: packaged Windows x64 app completed.
- `scripts/capture-native-pet.ps1`: native packaged screenshot confirmed the
  transparent bottom-right overlay and Island coexist without opening/focusing
  the control center. Evidence is generated at
  `output/evidence/pet-native.png` (ignored by Git).
- `scripts/measure-desktop-pet.ps1 -WarmupSeconds 12 -SampleSeconds 12`: same
  packaged build, pet disabled versus enabled; voice stack disabled and Gateway
  pointed at unreachable loopback in both modes to isolate Electron shell cost.

## Native resource evidence

Host: Windows 11 Pro, AMD Ryzen 5 3600X, 15.9 GiB RAM, Electron 43.4.0,
Marvi OS 0.4.15 win-unpacked.

| Metric                          | Pet disabled | Pet enabled |               Delta |
| ------------------------------- | -----------: | ----------: | ------------------: |
| Electron processes              |          6.0 |         7.0 |                +1.0 |
| Average aggregate working set   |   600.74 MiB |  869.01 MiB |         +268.27 MiB |
| Peak aggregate working set      |   603.06 MiB |  876.88 MiB |         +273.82 MiB |
| Average aggregate private bytes |   309.81 MiB |  379.89 MiB |          +70.08 MiB |
| CPU, percent of one core        |        50.0% |       50.0% | no measurable delta |

Aggregate working set double-counts mapped/shared Chromium pages across
processes; private bytes are the more useful incremental memory signal. An
earlier 8-second run with a 2× high-DPI backing canvas measured +55.10 MiB
private and +12.5% of one core. Switching to the atlas' native `192×208`
backing canvas removed that CPU delta in the longer repeat, while memory remains
material. The JSON result is generated at
`output/evidence/pet-resource-measurement.json` (ignored by Git).

## Decision gate

The feature must not be called shipped until the product owner selects one:

1. **Keep** the current optional renderer and accept its measured memory cost.
2. **Optimize** into a dedicated minimal renderer entry or native surface, then
   repeat off/on and long-idle measurements.
3. **Draft** the feature by keeping this branch/worktree out of release builds.

If kept, repeat the measurement with the full managed voice stack and a
60-minute idle soak before release.
