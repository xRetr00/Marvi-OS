# Phase 7 — First Windows Release

**Status:** in progress
**Depends on:** Phases 2 and 6

## Scope

- Extract and adapt the tested the predecessor assistant Windows update handoff.
- Test updates from multiple older releases and from interrupted updates.
- Package and publish the first Windows release of Marvi OS.

## Removed from scope

The durable job bridge to Marvi Agent for coding, research, and long-running
work is **dropped**, by decision on 2026-08-16. Marvi OS is an ambient voice and
vision assistant; delegating deep work to a separate coding agent is a different
product. ADR-001 already keeps the two runtimes independent, and nothing in the
shipped surface depends on the bridge.

## Implemented — the update handoff

- The small Tauri `marvi-bootstrap.exe` in `apps/updater` replaced the retired
  PowerShell handoff. It is both installer and updater, streams progress from a
  headless Rust core, maintains rollback snapshots, and refreshes itself only
  after a successful tagged update.
- `apps/desktop/src/main/updater.ts` starts the bootstrap outside packaged build
  output, passes the checkout/channel/PID/relaunch contract, and quits only
  after handoff succeeds. The bootstrap waits for the desktop and clears Marvi
  child processes before touching the checkout.
- The bootstrap UI renders a fixed manifest of real stages. Raw command output
  is a separate bounded/selectable stream behind Show details, so log lines can
  never impersonate stages or move the weighted progress bar. Failure opens the
  log and stays visible; verified success closes automatically.
- The status-bar version popover and About share quiet startup/focus/periodic
  checks, channel selection, current/target SHAs, release integrity, exact
  commit count, bounded grouped commit details, last result, and guarded update
  actions. A result is consumed once rather than re-announced on every launch.

## Evidence

Run against a throwaway git remote, exercising each safety path:

| Path | Result |
|---|---|
| Already current | `ok — Already up to date.` |
| Local changes present | `skipped` — refuses rather than discarding the user's edits |
| Real update | `ok`, HEAD moved `70637a7 -> 66c5ab4`, rebuilt |
| Build fails on the new commit | `failed — The build failed. The previous version was restored.` and HEAD is back at the working commit |
| App never exits | `aborted — Marvi OS did not exit within 60s` and the checkout is untouched |

A real bug this testing caught: Windows PowerShell 5.1's `-Encoding utf8` writes
a BOM, and `JSON.parse` rejects it. The handoff spawns `powershell` (5.1, not
`pwsh`), so every update result would have been silently unreadable and the user
would have seen nothing after an update. The script now writes plain UTF-8, the
Electron side strips a BOM defensively, and a regression test covers it.

The current updater workspace suite, focused desktop handoff/changelog tests,
and the live matrix above cover this boundary. The 720×520 browser-only safe
preview is checked in both stage-only and split live-output states; it performs
no install or checkout mutation.

## Acceptance evidence required

- ~~An update applied from an older release~~ — done: HEAD moved forward and
  rebuilt against a real remote.
- ~~An interrupted or failing update leaves the previous installation
  working~~ — done: build failure rolls back, and a live app aborts the handoff.
- ~~A packaged build starts and runs~~ — done: `scripts/build-desktop.ps1`
  produced `marvi-os-desktop-0.1.0-dev.0-setup.exe` (96.5 MB) and the unpacked
  build launched with six processes, responding, at 542.6 MB aggregate working
  set, exiting cleanly with no strays.

## Still required

- A human pass over the packaged app: confirm the tray menu and that About
  reports version, commit, build time, and channel. Launch and process
  lifetime are verified; the visual check is not something to claim remotely.
- Cut the first tagged release with `scripts/release.ps1`, which is the
  remaining step and is deliberately left to you — publishing is your call.
- Signing uses whatever certificate signtool finds; a real publisher
  certificate is not configured.
