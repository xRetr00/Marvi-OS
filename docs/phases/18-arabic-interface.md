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

## Milestone 2 — Static renderer copy

- [x] Extract static JSX text and accessible attributes across renderer pages.
- [x] Translate them in the Arabic catalogue and preserve English fallback.
- [x] Add a source audit that fails when an extracted key has no Arabic entry.
- [x] Keep code and technical identifiers unchanged where translation would
      corrupt them.

Evidence: source audit covers 977 Arabic catalogue entries, including 399
standalone JSX labels, 434 static attributes, and 148 mixed-content fragments.
On 2026-09-22, desktop typecheck, renderer build, `git diff --check`, and all
609 desktop tests passed.

## Milestone 3 — Dynamic copy and formats

- [ ] Localize dynamic renderer status and error copy.
- [ ] Localize Gateway-written text displayed in the app.
- [ ] Route remaining date, number, duration, and relative-time UI through the
      interface locale.

## Milestone 4 — Direction and acceptance

- [ ] Isolate paths, URLs, model names, and identifiers in mixed Arabic prose.
- [ ] Review control center, settings, Chat, and Island visually in RTL.
- [ ] Run desktop and Gateway suites, build, and `git diff --check`.
- [ ] Update README, UI contract, upstream ledger, and implementation log.
