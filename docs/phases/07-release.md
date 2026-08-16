# Phase 7 — First Windows Release

**Status:** in progress
**Depends on:** Phases 2 and 6

## Scope

- Extract and adapt the tested Marvi/Hermes Windows update handoff.
- Test updates from multiple older releases and from interrupted updates.
- Package and publish the first Windows release of Marvi OS.

## Removed from scope

The durable job bridge to Marvi Agent for coding, research, and long-running
work is **dropped**, by decision on 2026-08-16. Marvi OS is an ambient voice and
vision assistant; delegating deep work to a separate coding agent is a different
product. ADR-001 already keeps the two runtimes independent, and nothing in the
shipped surface depends on the bridge.

## Implemented — the update handoff

- `scripts/desktop-update/windows.ps1`, adapted from the tested Hermes handoff
  with provenance in `docs/UPSTREAM.md`. It lives in the checkout on purpose: a
  frozen installer cannot fix its own updater, so update bugs would outlive
  their fixes. Each successful update also refreshes the updater.
- `apps/desktop/src/main/updater.ts` builds the handoff and quits. The
  `cmd /d /s /c start "" /min powershell` wrapper is load-bearing — a bare
  detached, hidden PowerShell is killed before `-File` is read — so its exact
  shape is asserted in tests rather than left to runtime.
- An Updates page showing version, channel, whether this install can self-update
  at all, and the result of the last attempt, consumed once so it is not
  re-announced on every launch.

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

11 updater tests plus the live matrix above.

## Acceptance evidence required

- ~~An update applied from an older release~~ — done: HEAD moved forward and
  rebuilt against a real remote.
- ~~An interrupted or failing update leaves the previous installation
  working~~ — done: build failure rolls back, and a live app aborts the handoff.
- A packaged build starts, reaches the tray, and reports its version, commit,
  and channel in About. **Still open** — needs a real `build:win` run and a
  launch on this machine.

## Still required

- Run `scripts/build-desktop.ps1` and launch the packaged installer to confirm
  tray, version, commit, and channel.
- Code signing is not configured; the first release will be unsigned.
