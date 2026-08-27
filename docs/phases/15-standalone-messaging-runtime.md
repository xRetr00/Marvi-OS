# Phase 15 — Standalone messaging runtime

Status: complete

## Outcome

Marvi OS ships messaging as an application resource. The repository contains
9,382 ordinary vendored source files at pinned commit
`61977bb4d6b97ab2aece57d2405fa2f0b19e3ae0`, with no `.gitmodules`, gitlink, or
nested `.git`. The build stages those exact files, standalone CPython 3.11.15,
and 140 resolved packages under `resources/messaging`.

Electron locates `process.resourcesPath/messaging/source` and starts the sibling
`python/python.exe` with `-m hermes_cli.main gateway run`. `UV_OFFLINE`,
`PIP_NO_INDEX`, `PYTHONNOUSERSITE`, and the managed-runtime marker make source
or dependency acquisition unavailable during launch.

## Evidence

- `npm run build:unpack` completes with the messaging payload in the unpacked app.
- The staged source count equals the 9,382 Git-tracked vendored files.
- The packaged interpreter completes `gateway run --help` with downloads disabled.
- Desktop lifecycle tests, Gateway installer-argument tests, updater tests, and
  repository-wide source/update scans cover the boundary.
