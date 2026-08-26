# Phase 16 — Marvi-owned messaging boundary

Status: complete

## Acceptance boundary

- Electron launches `messaging/python/python.exe -m marvi_messaging.main` only.
- `marvi_messaging.lifecycle` invokes `gateway.run.start_gateway` directly and
  owns graceful completion, planned stop, and external-supervisor semantics.
- setup and health are Marvi commands backed by stable Marvi Python APIs.
- pairing list/approval is a Marvi API surfaced in Settings; the one-time code
  stays hashed in the private vendor store.
- no Marvi runtime file imports or invokes `hermes_cli.main`.
- legacy environment/config names are isolated inside the private vendor bridge;
  Electron and renderer contracts are Marvi-named.
- packaged offline execution proves the owned command and exact separated payload.
- the derived `/update` and detached CLI restart paths are unreachable under the
  Marvi runtime marker; application updates remain owned by Marvi's updater.
- messaging adapters, sessions, streaming, attachments, approvals, schedules,
  and toolsets retain the complete pinned implementation beneath the facade.

## Evidence

- `services/messaging/tests/test_marvi_runtime.py`: 6/6 boundary tests pass,
  including direct lifecycle reuse, pairing request approval, restart fallback,
  update denial, setup ownership, and the absence of `hermes_cli.main`.
- Desktop Vitest: 40 files and 262 tests pass; both TypeScript targets and the
  production Electron/Vite build pass; focused ESLint has zero errors.
- The unpacked Windows artifact runs `gateway run --help`, `health`, and
  `pairing list` using its own Python with `UV_OFFLINE=1`,
  `UV_PYTHON_DOWNLOADS=never`, and `PIP_NO_INDEX=1`.
- Artifact inventory matches its manifest: 9,382 vendored files, 7 Marvi runtime
  files, no nested `.git`, no legacy `source` directory, and no smoke profile.
- Compiled Electron contains `marvi_messaging.main` and `MARVI_MESSAGING_HOME`;
  it contains neither `hermes_cli.main` nor `HERMES_HOME`.
