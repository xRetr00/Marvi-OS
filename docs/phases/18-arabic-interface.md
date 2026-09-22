# Phase 18 — Arabic interface

Scope: control center, Dynamic Island, Chat, renderer settings, and user-facing
Gateway prose. Speech recognition, synthesis, wake word, and Arabic memory
storage/search are outside this phase. The memory agent reads input in any
language and is instructed to store facts in English.

## Milestone 1 — Locale and RTL foundation

- [x] Persist English/Arabic separately from speech language and sync windows.
- [x] Set document language and direction before the first React render.
- [x] Package Noto Sans Arabic, use logical CSS properties, and keep code LTR.
- [x] Translate the shell, primary Chat controls, and Island confirmations.
- [x] Use `Intl` for the shared number, date, and relative-time helpers.
- [x] Test locale behavior, typecheck, build, and desktop regression suite.

Evidence: desktop typecheck, `electron-vite build`, 607 desktop tests, and 21
Gateway remembering tests passed on 2026-09-22. RTL visual review remains for
Milestone 3.

## Milestone 2 — Complete copy and formats

- [ ] Translate reachable renderer UI copy and preserve English fallback.
- [ ] Localize Gateway-written text displayed in the app.
- [ ] Route remaining date, number, duration, and relative-time UI through the
      interface locale.
- [ ] Add coverage that detects untranslated catalogue entries and reachability
      gaps.

## Milestone 3 — Direction and acceptance

- [ ] Isolate paths, URLs, model names, and identifiers in mixed Arabic prose.
- [ ] Review control center, settings, Chat, and Island visually in RTL.
- [ ] Run desktop and Gateway suites, build, and `git diff --check`.
- [ ] Update README, UI contract, upstream ledger, and implementation log.
