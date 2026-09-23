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
Gateway remembering tests passed on 2026-09-22.

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

- [x] Localize dynamic renderer status and error copy.
- [x] Localize Gateway-written text displayed in the app.
- [x] Route remaining date, number, duration, and relative-time UI through the
      interface locale.

Evidence: renderer-bound Gateway health copy, provider errors, tool activity,
room diagnosis, usage, update, weather, memory, resource, schedule, and visitor
formats are locale-aware. Focused behavior tests and desktop typecheck passed on
2026-09-23.

## Milestone 4 — Direction and acceptance

- [x] Isolate paths, URLs, model names, and identifiers in mixed Arabic prose.
- [x] Review control center, settings, Chat, and Island visually in RTL.
- [x] Run desktop and Gateway suites, build, and `git diff --check`.
- [x] Update README, UI contract, upstream ledger, and implementation log.

Evidence: Chromium renderer captures at 1440×1000 cover the RTL control center,
Preferences, and Chat, plus the 640×320 confirmation Island. They are stored in
`docs/evidence/arabic-rtl-*.png`. Desktop typecheck and production renderer
build passed; all 615 desktop tests passed after retrying one Windows process
ownership timeout, and 52 Gateway remembering tests passed on 2026-09-23.

## Milestone 5 — Independent layout direction

- [x] Keep Follow language as the default and preserve the complete Arabic RTL
      layout.
- [x] Add explicit RTL and LTR shell overrides, persisted and synchronized
      independently from language.
- [x] Keep Arabic prose RTL and technical runs isolated when Arabic uses an LTR
      shell.
- [x] Add behavior coverage and capture the Arabic LTR shell for review.
