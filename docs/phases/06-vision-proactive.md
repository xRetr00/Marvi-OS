# Phase 6 — Vision and Proactive Behavior

**Status:** in progress
**Depends on:** Phases 3 and 4

## Scope

- Always-on local presence and gesture inference with bounded resource use.
- Raw camera frames remain local; selected frames publish only for an explicit
  active vision task.
- Focus-safe proactive room/world notifications through the Island.

## Acceptance evidence required

- Camera privacy boundary test, idle GPU/RAM measurement, gesture/presence
  accuracy sample, and proof that background events never focus the main window.

## Implemented — the REAL-AGENCY mind

The proactive half of this phase is built. Vision is not.

- `marvi_gateway.journal`: a durable event journal. Room transitions, account
  items, and reflections land here with provenance and trust before anything
  reasons about them, and the same event arriving twice is one event.
- `marvi_gateway.policy`: `REAL-AGENCY.md`'s five conditions as ordered, named
  rules — `initiative-paused`, `daily-budget`, `conversation-active`,
  `cooldown`, `quiet-hours`, `nobody-present`, `allowed`. Every verdict names
  the rule that produced it, so both "why did Marvi speak" and "why did Marvi
  stay quiet" have real answers.
- A surface ladder from `silent` through `remember`, `activity`, `island`,
  `speak`, to `propose`. Each event kind has a ceiling; an unknown event kind
  can never be louder than `activity`, and untrusted content can never reach
  `propose`. Untrusted content may inform, never command.
- `marvi_gateway.mind`: the turn. Reads pending events, applies the policy,
  takes the least intrusive useful action, and records trigger, rule, surface,
  provider, latency, and cost. An idle tick decides nothing and touches no
  model. The mind proposes; anything with a side effect still goes back through
  the tool router, so it cannot bypass confirmation by "deciding" to.
- An optional LLM deliberation seam that may only make a decision **quieter**.
  The policy ceiling is not something a model gets to argue with, and its cost
  counts against the same daily budget.
- `marvi_gateway.initiative`: APScheduler 3.11.3 driving four bounded ticks —
  ingest, mind, reflect, consolidate. Every job is guarded, so one failure is
  recorded and skipped rather than killing the schedule. Pausing stops
  decisions but not observation, so resuming shows what was missed.
- A Mind page and `/initiative`, `/mind/decisions`, `/mind/tick` endpoints, so
  initiative can be paused and every decision inspected.

## Evidence

| Gate | Result |
|---|---|
| Duplicate suppression | the same event twice is one event; accepted again only after the dedupe window |
| Paused initiative | outranks every other rule; events still observed, decisions stop |
| Untrusted authority | an email may reach the Island and can never reach `propose` |
| Live conversation | speech downgraded to Activity rather than talking over the user |
| Cooldown | a repeat inside the window is downgraded, and expires correctly |
| Quiet hours / absence | speech downgraded to a glanceable surface |
| Daily budget | exhaustion silences later events the same day; LLM cost counts against it |
| Unknown event kind | never louder than Activity |
| LLM deliberation | may quieten a decision, never amplify it |
| Idle tick | decides nothing, records nothing, calls no model |
| Job failure | recorded and cleared on recovery; the schedule survives |

Automated coverage: 33 tests across the journal, policy, mind, and scheduler.

## Still required

- All vision work: presence and gesture inference, the camera privacy boundary,
  idle GPU/RAM measurement, and the accuracy sample.
- LLM deliberation is wired as a seam but no provider is attached, so decisions
  are deterministic today.
- The proactive surfaces resolve to decision records; routing `speak` into an
  actual spoken turn through the LiveKit session is not connected yet.
- Letta was evaluated for this role and rejected; see ADR-018.
