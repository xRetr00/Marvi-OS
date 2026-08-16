# Phase 6 — Proactive Behaviour and the Mind

**Status:** complete
**Depends on:** Phases 3 and 4

Vision moved to [`08-vision.md`](08-vision.md); this phase is cognition only.

## Scope

- Event-driven cognition: a durable journal, a relevance and policy boundary,
  and a mind turn that decides the least intrusive useful surface.
- Focus-safe proactive room and world notifications.
- Proactive speech that does not borrow the full-duplex voice stack.

## Acceptance evidence required

- Every proactive decision names the rule that produced it, including silence.
- Background events never steal focus or interrupt a live conversation.
- Background thinking has explicit time and cost budgets.

## Implemented — the REAL-AGENCY mind

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

## Proactive speech (ADR-019)

`speak` now reaches the speakers. Proactive announcements deliberately do not
use the Phase 3 streaming stack: there is no first-token race and nothing to
barge into, so paying GPU streaming cost would be wrong. They use kyutai
PocketTTS on the CPU — measured here at 1.5 s to load and **0.811 RTF** at
24 kHz on a single torch thread.

The audio publishes into the same LiveKit room the desktop client is already
subscribed to, rather than straight to the sound card. That is the important
part: the microphone is always live for the wake word, so a sentence played
outside the room would be transcribed as if the user had said it. Routing
through the room means the client's WebRTC echo cancellation — the same
mechanism Phase 3 depends on — cancels it. This is the point where Phase 6
touches Phase 3 again.

If speech fails for any reason the decision is not lost; it drops to the Island
so the user still sees it.

## Deliberation (live)

The LLM seam now has a provider: OpenCode Go through the same
OpenAI-compatible boundary the voice agent uses. Verified live — an alarm event
produced `{"worth_it": true, "say": "The bedroom alarm is going off."}` in
4.1 s, and that sentence is what Marvi speaks.

`deepseek-v4-flash` is a reasoning model and its latency varies; one run
exceeded the 20 s budget and fell back to the deterministic verdict, which is
the designed degradation rather than a failure. Additional providers, OAuth,
and auxiliary models are future work behind `deliberator_from_env`.

## Still required

- Nothing for this phase. Vision is Phase 8; more providers are a later update.
