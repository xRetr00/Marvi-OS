# Phase 14 — Messaging companion

Status: complete

## Outcome

Ship the messaging gateway from `D:\hermes-agent` end to end without a partial
rewrite. The exact source commit is a repository-owned Git submodule, and the
desktop supplies lifecycle, setup, status, and private-profile controls.

## Acceptance gates

- A fresh clone and the bootstrap updater materialize the recursive submodule.
- The desktop makes no messaging network connection until setup exists and the
  user explicitly enables it.
- Setup runs the pinned upstream wizard unchanged; platform credentials never
  cross renderer IPC.
- Electron supervises and tears down the entire messaging process tree.
- The source commit, adapter inventory, profile path, configuration state, and
  service failures are visible in the control center.
- The pinned source retains its complete sessions, delivery, attachment,
  command, approval, scheduling, and tool behavior.
- Desktop lifecycle tests, updater tests, and selected upstream gateway/tool
  contract tests pass.

## Evidence

- The gitlink and runtime pin both resolve to
  `61977bb4d6b97ab2aece57d2405fa2f0b19e3ae0`; the desktop contract test reads
  the materialized checkout and discovers 24 platform values from its source.
- Desktop: changed-file ESLint passed with zero errors; TypeScript typecheck
  passed; all 40 Vitest files passed (259 tests); the production Electron build
  completed.
- Bootstrap: 59 unit tests, 6 install-flow tests, and 6 update-flow tests passed
  serially; 2 live machine-mutating tests remained intentionally ignored. The
  new clone test creates a real nested Git repository and proves
  `--recurse-submodules` materializes its pinned file.
- Pinned upstream: 80 selected platform-command, toolset, approval, and API
  toolset tests passed; 4 optional cases skipped. `marvi gateway run --help`
  from the pinned checkout confirmed the `--external-supervisor` contract.
- One additional upstream topic-session test fails at the pinned commit because
  it observes a new `asyncio.to_thread` task. The identical test fails in the
  original `D:\hermes-agent` checkout at the same commit, proving it is an
  upstream baseline defect rather than a submodule or Marvi OS integration
  regression. The vendored source remains unchanged.
- `git diff --check` passed. Full-repository ESLint still emits the checkout's
  pre-existing CRLF Prettier warnings; changed files pass the error gate.

## Commit

`feat: add complete messaging companion`
