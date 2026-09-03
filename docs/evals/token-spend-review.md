# Token spend review

Scope: every path in this repo that can spend LLM tokens, quantified against
real data, plus a design recommendation for what should gate the Mind's model
call. No code was changed to produce this review.

## Method and a caveat about the "live" evidence

The task brief pointed at `http://127.0.0.1:8765/mind/decisions?limit=200` as a
running Gateway. At review time (2026-09-03, mid-morning local) nothing was
listening on port 8765 — `curl`/`Invoke-RestMethod` both got connection
refused, and the only Marvi process alive was `marvi-bootstrap`. So this
review reads the same data the endpoint would have served, straight from disk:

- `C:/Users/xRetro/AppData/Local/Marvi-OS/journal.sqlite3` — tables `events`
  (12,135 rows) and `decisions` (12,135 rows), 2026-08-23 through 2026-09-03.
  This is the Mind's own ledger; nothing outside `mind.py` writes to it.
- `C:/Users/xRetro/AppData/Local/Marvi-OS/latency.jsonl` — 4,065 rows, a
  latency-only instrumentation log (`services/gateway/src/marvi_gateway/latency.py`)
  covering the `voice` and `chat` surfaces. Only `chat` rows carry token
  counts; `voice` rows are timing-only (`tokens: 0` throughout).
- `C:/Users/xRetro/AppData/Local/Marvi-OS/chat.sqlite3` — the typed-chat
  thread store, for cross-checking.

There is no comparable ledger for memory reflection, dreaming, rephrasing, the
standing brief, continuity notes, per-turn memory extraction, skill proposals,
or cron jobs — none of those write to `journal.sqlite3`, and `latency.jsonl`
only instruments two surfaces. So the number in this report that can be
stated with real, measured confidence is the Mind's; everything else is
bounded from the code (max-token constants, gating conditions, schedule
intervals) because no usage ledger exists to measure it against. That gap is
itself a finding — see [What isn't measured](#what-isnt-measured).

**A timing note that shapes this whole report.** `git log` shows the two
commits that most directly bear on Half 1's central finding —
`fcfd52ff` ("enhance activity tracking and reporting in voice-session
management", which is where `"room:vision_sleep_state": "silent"` was added
to `SURFACE_CEILING`) and `d0e51f23` ("enhance decision-making efficiency by
refining worth_thinking_about logic") — both landed **today**, at 07:38 and
07:43 local time, i.e. minutes before this review started. The journal data
below runs up to 07:49 local. So this review is, in large part, independent
confirmation of a fix that was already made in this session, with the
before/after numbers to show what it's worth — and a look at what it does and
doesn't cover.

---

## Half 1 — where tokens actually go

### 1. The Mind's deliberation — `mind.py` / `deliberate.py` / `policy.py` / `initiative.py`

**Trigger.** `Initiative` runs an APScheduler interval job named `"mind"`
every `MIND_MINUTES = 2` minutes
(`services/gateway/src/marvi_gateway/initiative.py:29,358-361`), calling
`Initiative.run_mind()` → `Mind.tick()`
(`services/gateway/src/marvi_gateway/mind.py:112-256`). The tick itself is
cheap when idle — `journal.pending()` returns nothing and the function returns
immediately (`mind.py:121-125`) — but it fires unconditionally every two
minutes, 720 times a day, whether or not anything happened.

**What actually costs a model call.** For each pending event (up to
`MAX_EVENTS_PER_TURN = 10` per tick, `mind.py:30`), a deterministic policy
(`policy.evaluate`, `services/gateway/src/marvi_gateway/policy.py:184-233`)
computes a capped `surface` first, at zero cost. Only if that surface clears
`_worth_thinking_about()` (`mind.py:37-64`) does `Mind.tick` call
`self.deliberate(event, verdict)` (`mind.py:170-173`), which is
`Deliberator.__call__` (`deliberate.py:89-157`) — one call through
`CognitionHarness.ask` (`cognition.py:131-210`), capped at
`MAX_OUTPUT_TOKENS = 120` (`deliberate.py:41`) for the final answer, but able
to spend up to `MAX_TOOL_ROUNDS = 3` rounds of up to
`MAX_TOOL_CALLS_PER_ROUND = 4` tool calls each (`cognition.py:43-44`) if the
model reaches for `memory_recall`, `web_search`, etc. (`MIND_TOOLS`,
`cognition.py:26-34`) before answering — which is why a single "was this
worth mentioning" call can cost hundreds to low thousands of tokens rather
than the ~120 its final answer is capped at.

**The result is used, but only to go quieter.** `mind.tick` never accepts a
louder surface than the policy already allowed
(`if SURFACES.index(proposed) <= SURFACES.index(verdict.surface)`,
`mind.py:176-179`) — the model can turn a policy-allowed `activity` into
`silent`, never the reverse. So the call is never wasted in the sense of "the
answer was ignored"; it is used every time. The waste, measured below, is
that the answer is overwhelmingly "no", and a fixed-cost model call to hear
"no" is not free.

**Budget.** `InitiativeSettings.daily_token_budget` defaults to 200,000
tokens/day (`policy.py:38`), enforced in `evaluate()` before any model call
(`policy.py:198-201`) against `journal.tokens_since(day_start(now))`
(`mind.py:100`, `journal.py:220-225`). This budget **is measurably working**:
see below.

#### Measured, from `journal.sqlite3` (`events` × `decisions`)

Over the 11-day window in the journal, using the code's own day boundary
(`policy.day_start` — local midnight, i.e. UTC+03:00 on this machine, **not**
the UTC calendar day):

| local day | decisions | tokens spent |
|---|---:|---:|
| 2026-08-28 | 4,260 | 200,346 |
| 2026-08-29 | 2,335 | 200,201 |
| 2026-08-30 | 238 | 200,107 |
| 2026-08-31 | 622 | 200,151 |
| 2026-09-01 | 109 | 83,510 |
| 2026-09-02 | 4 | 4,756 |
| 2026-09-03 (partial) | 21 | 22,209 |
| all 11 days | 12,135 | **911,280** |

Four consecutive days (Aug 28–31) each land within a few hundred tokens of
the 200,000 ceiling — the daily budget is doing exactly what it's supposed to
do, capping spend right at the configured line rather than drifting past it.
That is a genuine positive finding: the budget mechanism works as designed.

What it was spending the budget *on*:

```
provider family        count    tokens
llm-succeeded (real)      946   911,280
llm-failed (provider err)4,764        0
deterministic (blocked)  6,425        0
```

Of the 946 calls that actually completed and cost tokens:

```
surface (post-deliberation)   count    tokens     avg/call
silent                           921   878,289      953.6
activity                          25    32,991    1,319.6
```

**97.4% of the real, paid-for LLM calls ended in `silent`, accounting for
96.4% of every token the Mind has ever spent** in this journal. By event kind,
joining `decisions` back to `events`:

```
kind                          calls   tokens
room:vision_sleep_state         720   691,655   (75.9% of all tokens spent)
room:vision_visitor_seen        133   129,876   (14.2%)
room:light_changed               34    32,680
room:device_offline              15    12,334
room:presence_detected            9    12,149
room:presence_cleared             8     9,935
room:mode_changed                13     7,161
room:room_entry                   6     6,661
memory:conclusion                 3     4,495
accounts:googlecalendar           1     1,706
memory:reflection                 1     1,624
room:vision_gesture               3     1,004
```

`room:vision_sleep_state` and `room:vision_visitor_seen` together are **90.1%
of every token this feature has ever spent**, and `vision_sleep_state` alone
is also, by a wide margin, the loudest source in the journal by raw event
count: 11,447 of 12,135 events (94.3%) are one Smart Room sensor firing on
every sleep/wake transition. This matches the `mind.py:47-58` docstring's own
measurement (written before today's fix landed) almost exactly — the exact
failure it names ("85% spent on three room sensors, every one of them ending
`silent`") is what the fresh data confirms at larger scale.

Separately: **83% of every deliberation the Mind attempted (4,764 of 5,710)
failed at the provider call** (caught as `ProviderCallError`,
`deliberate.py:122-132`, falling back to the deterministic verdict at zero
cost). That's not a token-spend problem — failed calls cost nothing — but it
is a reliability signal worth someone's attention separately: only 1 in 6
attempted deliberations actually got an answer back.

#### What today's two commits change, and what's still open

`fcfd52ff` added `"room:vision_sleep_state": "silent"`,
`"room:presence_detected": "silent"`, and `"room:presence_cleared": "silent"`
to `SURFACE_CEILING` (`policy.py:80,82-83`) — these previously had **no
entry** and fell through to the default `"activity"` ceiling
(`policy.py:198`, and the docstring at `policy.py:64-73` says so explicitly).
`d0e51f23` tightened `_worth_thinking_about()` so that anything capped at
`"activity"` or below never reaches `deliberate()` at all
(`mind.py:60-64`: `SURFACES.index(verdict.surface) > SURFACES.index("activity")`).

Recomputing eligibility under the *current* code against the same 12,135
historical events: only kinds capped `"island"` or louder can ever reach
`deliberate()` now. Of the observed kinds, that's `accounts:gmail:gmail` (4
events), `accounts:googlecalendar:googlecalendar` (23), and
`room:room_welcome` (6, capped `"speak"`) — **33 of 12,135 events (0.27%)**.
Every other kind observed in this journal — `vision_sleep_state` (11,447),
`vision_visitor_seen` (214), `light_changed` (104), `presence_detected` (96),
`room_entry` (71), `presence_cleared` (70), `device_offline` (42),
`vision_gesture` (32), `mode_changed` (21), `memory:conclusion`,
`memory:reflection` — is now capped `"silent"` or `"activity"` and is
excluded from `deliberate()` before any model is touched. Projected against
this historical mix, that is roughly a 99%+ cut in LLM-eligible event volume
for the Mind, and it should eliminate essentially all of the
`vision_sleep_state` / `vision_visitor_seen` spend going forward. This is a
projection from the historical event mix under the new code, not a new
measurement — the fix is too recent for a second measured window to exist
yet.

What the fix does **not** touch:

- `room:vision_visitor_seen` is capped `"activity"`, not `"silent"`
  (`policy.py:81`) — it is now excluded from deliberation (activity is not
  `>` activity), but it is still being *recorded* at `"activity"` surface on
  every occurrence, same as before. That's fine (activity is meant to be
  cheap/free), but worth noting it wasn't downgraded further the way the
  three others were.
- The daily budget is Mind-only. It does not see, and cannot cap, any other
  path in this document — reflection, dreaming, per-turn memory extraction,
  skill proposals, or cron jobs all spend against no shared ceiling. A user
  who adds a chatty cron job (see §10) has no budget backstop at all.
- The 83% provider-call failure rate is untouched by either commit and has
  nothing to do with token spend — it's a different problem (why is the
  configured provider failing 5 times out of 6?) worth its own look.

### 2. Memory reflection — `memory.py:1537-1594`

**Trigger.** APScheduler `"reflect"` job, every `REFLECT_HOURS = 6`
(`initiative.py:30,362-366`), calling `Initiative.run_reflect()` →
`MemoryStore.reflect(summarise=...)`.

**Gate before the model.** `reflect()` first runs a deterministic `GROUP BY`
over episodic memories (`memory.py:1546-1551`) and only calls the injected
`summarise` callback — `auxiliary.summarise_memories` →
`distil.ask(role="memory", ...)` (`auxiliary.py:184-208`) — if there's at
least one subject seen `PROMOTE_AFTER_REPEATS` times. If the model returns
nothing (unconfigured, cooling, malformed), the deterministic promotion
(`memory.py:1576-1589`) still runs — the model result is a genuine
enhancement, never a single point of failure.

**Bound.** One call per tick, capped at `MEMORY_TOKENS = 400` output tokens
(`auxiliary.py:43`). Runs at most 4x/day. Not measured in any ledger, but
bounded by construction to a few hundred tokens, a handful of times a day.

### 3. Dreaming — `dreaming.py` / `initiative.py:209-260`

**Trigger.** APScheduler `"dream"` job, every `DREAM_HOURS = 12`
(`initiative.py:33,368-371`) — deliberately slower than reflection, per the
module's own comment (`initiative.py:31-33`): "there is nothing to conclude
from a morning."

**Gate before the model.** `run_dream()` reads up to `WINDOW = 80`
(`dreaming.py:59`) memories accumulated since the last dream's watermark; if
fewer than `MIN_PREMISES = 2` (`dreaming.py:63`) are new, it returns early
**without** advancing the watermark or calling a model
(`initiative.py:227-229`) — so a quiet machine costs nothing, and the next
tick simply re-checks the same backlog rather than losing it.

**Bound.** One call, capped `MAX_OUTPUT_TOKENS = 2_000` (`dreaming.py:55`) —
the largest single-call cap in the codebase, because it's asked to read up to
80 memories and propose conclusions, entity links, and retirements in one
shot. At most twice a day.

**Result usage.** Genuinely used: conclusions and links are written to the
memory graph (`dreaming.apply`, `dreaming.py:224-251`), and the watermark only
advances after a completed dream, so nothing is silently dropped.

### 4. Rephrasing — `rephrasing.py`, opt-in

**Trigger.** Off by default (`MARVI_MEMORY_REPHRASE`, `rephrasing.py:72,121-122`).
When enabled, it runs twice: once as a pre-step inside `run_dream()`
(`initiative.py:233-238`, "before dreaming rather than after") and once on its
own via the same 12-hour `"dream"` tick's `run_rephrase()`
(`initiative.py:262-274`) — so an enabled installation pays for it up to
twice per dream cycle.

**Bound.** `BATCH = 40` memories per pass, `PER_CALL = 8` per model call
(`rephrasing.py:76,81`) — up to 5 calls of `MAX_OUTPUT_TOKENS = 1_200`
(`rephrasing.py:83`) each, i.e. up to 6,000 output tokens per enabled pass,
twice per 12-hour cycle if both call sites fire in the same tick.

**Result usage — a genuinely measured miss.** The module's own docstring
(`rephrasing.py:32-45`) reports running this over a 144-memory store and
measuring the effect on retrieval: 128 of 144 memories got new "words they'd
be asked for," and **the eval score on the eight test questions did not
move** — still 7/8, the same question still missing. The author's own
diagnosis is dilution (the added words are averaged into one embedding
alongside a much longer sentence and don't shift the vector enough to win).
This is the clearest self-documented "spent tokens, kept the receipt, the
result didn't change the outcome it was built for" case in the codebase — and
it's exactly why it shipped opt-in and off by default rather than as part of
the standard schedule.

### 5. Standing brief — `standing.py`

**Trigger.** `standing.ensure()` (`app.py:2882`), called from wherever a
session/turn checks the brief (`app.py:2876-2883`) — fires in a background
thread so no turn waits on it (`standing.py:195-201`).

**Gate before the model.** `stale()` (`standing.py:132-138`): rebuild only if
never built, older than `STALE_HOURS = 12`, or the store has moved by
`MOVED_BY = 8` memories since the saved brief. Otherwise `block()` reads the
cached text from disk at zero cost (`standing.py:204-225`).

**Bound.** One call, `READS = 120` memories in, capped at 400 output tokens
(`standing.py:163`), `MAX_CHARS = 900` (`standing.py:62`) on the way out. This
is a well-designed example: pay once for a paragraph that's valid for half a
day, read it for free on every turn. Worth citing as a positive pattern.

### 6. Continuity note — `continuity.py`

**Trigger.** Once per session, at session end:
`continuity.remember(continuity.summarise(cognition, exchanges))`
(`app.py:2495-2496`), backgrounded in a thread.

**Bound.** One call per session (not per turn), capped
`MAX_OUTPUT_TOKENS = 120` (`continuity.py:62`), and the model is told to
reply exactly `NOTHING` for small talk (`continuity.py:76-77`), with
`worth_keeping()` filtering near-miss non-answers before they're persisted
(`continuity.py:107-130`). On by default (`MARVI_SESSION_CONTINUITY`,
default "on", `continuity.py:83-84`), read from disk at zero cost on the next
session start (`continuity.py:148-159`) and expires after `STALE_HOURS = 8`
so a stale note never gets read back stale (`continuity.py:157-158`).

### 7. Per-turn background spend that is *not* gated — `remembering.py` / `learning.py`

This is the clearest un-gated, always-on-per-turn spend in the codebase, and
it is structurally the same shape as the Mind's now-fixed problem: pay a
model on every occurrence to usually hear "no."

**Memory extraction.** Every finished turn — chat (`chat.py:1332-1336`,
`chat.py:1499-1503`) and voice (`app.py:2502-2512` via `POST /memory/observe`)
— is hedaed to `Rememberer.observe()` (`remembering.py:383-393`), which queues
it for a worker thread that calls `remembering.extract()`
(`remembering.py:245-304`). The only gate before the model call is
`if client is None or not (user.strip() or assistant.strip())`
(`remembering.py:251-252`) — there is no heuristic for "this turn was just an
acknowledgement." Every real turn costs one call, capped
`MAX_OUTPUT_TOKENS = 700` (`remembering.py:60`), with up to `NEIGHBOURS = 8`
existing memories and up to `MAX_TURN_CHARS = 4_000` characters of the turn
itself (`remembering.py:54,58`) in the prompt. The system prompt itself
documents that "an empty array is the right answer most of the time"
(`remembering.py:73`) — i.e. the common outcome, like the Mind's, is spending
tokens to store nothing.

**Skill proposal — a second full call, same trigger.** Immediately after
extraction, if `propose_skills` is true (the default, `remembering.py:335`,
never overridden at its one construction site, `app.py:1031-1037`), the same
worker thread calls `learning.propose()` (`remembering.py:409-410,417-442`).
`propose()` has **no gate at all** beyond `client is not None and both texts
non-empty` (`learning.py:126-127`) — no acknowledgement filter, no "was
anything unusual about this turn" check. It sends the full exchange (up to
4,000 + 4,000 chars) plus the installed-skills listing, capped
`MAX_OUTPUT_TOKENS = 1_200` (`learning.py:52`), and its own prompt says the
right answer is `{"act":"none"}` "almost always" (`learning.py:71`).

Net effect: **every conversational turn that produces any real reply — not
just the interesting ones — currently costs two extra background model calls
beyond the reply itself**, each of which is documented, in its own system
prompt, as usually returning nothing. Because both run off a worker thread
(`remembering.py:395-416`) they cost no latency on the turn, but they cost
real tokens against whichever provider is configured, on every turn, with no
budget and no cheap pre-filter — unlike the Mind, which now has both.

### 8. Memory reader — `reading.py`, per-turn, gated

**Trigger.** Speculative recall on the voice path
(`services/agent/src/marvi_agent/session.py:1092-1119`, `_recall`,
`session.py:462`), gated first by `needs_memory(text)`
(`session.py:191-200`) — a plain acknowledgement-word check that skips recall
entirely for turns like "okay"/"thanks." When recall does fire, `reading.answer()`
(`reading.py:100-128`) is on by default (`reading.py:88-96`) and adds one more
model call, capped `MAX_OUTPUT_TOKENS = 160` (`reading.py:69`), over up to
`WIDTH = 8` retrieved memories (`reading.py:65`).

**Why this one is defensible even though it's per-turn.** Unlike §7, this one
is backed by a measurement in its own docstring (`reading.py:9-33`): against a
153-memory store, plain top-5 search answered 8/8 answerable questions but
also fabricated answers on both of the two unanswerable ones, while the
LLM reader correctly abstained on both. It also runs inside the speculative
prefetch window while the user is still speaking (`reading.py:38-49`), so it
is free in latency 98% of the time by the module's own measurement. It is
still a real, ungated-beyond-`needs_memory` per-turn token cost; it's included
here because it's one more call stacked on top of the two in §7.

### 9. Gatekeeping — `gatekeeping.py`, and presence resolution — `presence.py` (two good examples)

**Ingest gatekeeper.** `AccountIngest` calls `gatekeeping.worth_keeping()`
(`ingest.py:785`) once per ingest poll (every `INGEST_MINUTES = 10`,
`initiative.py:28,354-357`), batched `BATCH = 20` items per call
(`gatekeeping.py:54`), capped `MAX_OUTPUT_TOKENS = 400`
(`gatekeeping.py:56`) — one call per batch of new items, not one per item,
and it only runs when the poll actually returns something. Fails open (keeps
everything) if the model is unreachable (`gatekeeping.py:118-131`), which is
the right direction for "don't silently lose a bill or an appointment," but
means an unreachable provider costs nothing rather than costing correctness —
a reasonable tradeoff, noted for completeness.

**Mid-conversation memory gate.** `gatekeeping.worth_remembering()`
(`gatekeeping.py:239-264`) runs synchronously when the `memory_remember` tool
fires mid-turn, capped at 64 output tokens (`gatekeeping.py:249`) — small and
bounded, on the interactive path but cheap.

**Presence resolution — the best pattern in the codebase.**
`presence.read()` (`presence.py:203-219`) calls a model **only when sensors
actually disagree or an unrecognised face is present**
(`if (conflict or unknown) and client is not None`, `presence.py:216-218`);
when every sensor that has an opinion agrees, `_arithmetic()` resolves it
deterministically at zero cost (`presence.py:219`, and the module docstring
at `presence.py:20-26` states the design goal explicitly: "A model is asked
*only* when the signals conflict... this runs on a poll and a model call per
poll would be both slow and expensive.") This is the "escalate only on
disagreement" pattern the Mind now approximates via surface ceilings, applied
at the point of *reading* a sensor rather than after the fact. It is the
single cleanest example in this codebase of the pattern this report
recommends for the Mind in Half 2.

### 10. Scheduled cron jobs — `schedule.py`, `CronAgentExecutor` (user-configured, unbounded)

**Trigger.** Explicit user-authored cron schedules (per the commit log,
"cron opt-in and a cron CLI"). Each firing runs `CronAgentExecutor.__call__`
(`schedule.py:418-449`), a full multi-round tool-calling agent loop, up to
`MAX_AGENT_ROUNDS = 5` (`schedule.py:33`), with no `max_tokens` cap on any
individual call and no reference to `InitiativeSettings.daily_token_budget`
or any other budget anywhere in the file. Cost scales directly with however
often the user schedules a job and how many tool rounds it needs — this is
the one path in the review where the user has full control over frequency
(it's their cron entry) but the system provides no backstop if that frequency
turns out to be a mistake (e.g. a job scheduled every 5 minutes that always
needs its full 5 rounds).

### 11. The conversational turn itself — `chat.py` / `services/agent/.../session.py`

This is the "real" spend the rest of the system exists to serve, and it is
inherently one call (or a short tool-round loop, `MAX_TOOL_ROUNDS = 8`,
`chat.py:76`) per user utterance — demand-driven, not a background cost.
Measured from `latency.jsonl`: 74 `chat` calls totalling 22,548 tokens
(avg 305/call) and 3,991 `voice` turns (tokens not recorded in this log) over
the Aug 20–Sep 3 window. `chat.sqlite3` currently holds only 4 assistant
messages, so the 74-call figure in `latency.jsonl` spans more history/testing
than what's in the live thread store — the two aren't reconcilable to an
exact count, but both agree this surface is lightly used relative to voice.
One extra call happens once per new chat thread: `distil.title()`
(`chat.py:339-353`), capped `TITLE_TOKENS = 40` (`auxiliary.py:42`), once per
thread, not per turn.

### 12. Vision/screen reading and one-off memory import — user- or tool-triggered, out of scope for "waste"

`screen.py`'s `read_screen` tool (`screen.py:98-134`) fires only when the
model calls it in response to an explicit user request ("what does this
say"), one image + question per call, via the `vision` role. `memory_import.organise()`
(`memory_import.py:447-472`) runs only when a user explicitly imports memories
from elsewhere, batched. Neither is a background or timer-driven cost;
included for completeness of the map, not flagged as waste.

### What isn't measured

`journal.sqlite3` records only what `Mind.tick` decides — nothing from §2–10
above writes a decision row, so there is no ledger anywhere in this
installation for reflection, dreaming, rephrasing, standing-brief rebuilds,
per-turn memory extraction, skill proposals, the memory reader, gatekeeping,
or cron jobs. `latency.jsonl` adds token counts for `chat` only; `voice` rows
in it carry `tokens: 0`. Every number in §2–10 is therefore a bound derived
from the code (max-token constants and gating logic), not a measurement — in
contrast to §1, which is a real measurement because the Mind is the one
subsystem with its own persistent record. If the goal is to actually see
where the other ~half of the system's tokens go, the cheapest fix is
mechanical: have `remembering.extract`, `learning.propose`, `distil.ask`
(shared by seven callers), and `schedule.CronAgentExecutor` each write one row
to a shared ledger the way `mind.py` already does — the schema in
`journal.sqlite3`'s `decisions` table is already the right shape to reuse.

---

## Half 2 — when should an agent actually call an LLM

Four bodies of current practice, each with sources, followed by the design
question.

### LLM as a last resort / deterministic-first

The consistent shape across recent agent-architecture writing is that the
model should sit *behind* a deterministic control layer, not in front of it —
called for bounded sub-tasks it's actually needed for, never to decide whether
to act at all. A "Blueprint First, Model Second" framework frames this
directly: the LLM handles bounded, complex sub-tasks *within* a workflow but
never decides the workflow's path, precisely because sampling from a token
distribution makes the model's own next action unpredictable in a way
deterministic code isn't ([arxiv.org/html/2508.02721v1](https://arxiv.org/html/2508.02721v1)).
A parallel line of work on deterministic control planes for coding agents
makes the same argument from the governance side: pre-execution state-machine
gates that block out-of-policy paths *before* the model is invoked, rather
than trusting the model to police itself after the fact
([arxiv.org/html/2606.26924v1](https://arxiv.org/html/2606.26924v1)).
Marvi's own `policy.py` is already this pattern for the Mind — a deterministic
ceiling computed before any model call, which the model may only narrow. The
gap this report found is that `remembering.py`/`learning.py` (§7) have no such
layer at all.

### Event-driven vs. polling loops

Polling is described in current practice as "the naive solution" — an agent
checking a queue or inbox on a fixed interval regardless of whether anything
changed — versus an event-driven agent that "sleeps until the system wakes it
with a specific task," with reported latency reductions of 70–90% and
near-zero idle compute cost ([Airbyte, "Event-Driven vs. Polling Architectures
for Agent Triggers"](https://airbyte.com/blog/comparing-architectures-for-agent-triggers);
[Fastio, "Event-Driven AI Agent Architecture Guide"](https://fast.io/resources/ai-agent-event-driven-architecture/)).
The important caveat, directly relevant here: moving to an event trigger only
helps if the *relevance* check moves with it. "If every source event still
gets dumped into the agent and the LLM decides what matters, you've mostly
moved the polling problem downstream. The better approach is to register
filters once, let a small event layer watch noisy streams, then wake the agent
only with the matched event"
([agentblueprint.substack.com](https://agentblueprint.substack.com/p/event-driven-vs-polling-architectures)).
This is exactly the distinction between the Mind's *tick* (a 2-minute timer,
cheap to run because it's an empty-queue check most of the time) and the
Mind's *deliberation call* (which the fix landed today finally keeps off of
anything the filter layer — `SURFACE_CEILING` — has already ruled uninteresting).

### Routing and cascades — small model first, escalate on uncertainty

Cascaded/routed inference sends a query to the cheapest model first and
escalates only when its own confidence is low, using token-probability or
verifier-based uncertainty as the escalation signal; reported results include
45–85% cost reduction at roughly 95% retained quality, and one combined
quality/cost/uncertainty approach reaching 97% of a frontier model's accuracy
at 24% of its cost ([arxiv.org/pdf/2606.27457](https://arxiv.org/pdf/2606.27457),
"Cluster, Route, Escalate"; [tianpan.co, "LLM Routing and Model
Cascades"](https://tianpan.co/blog/2025-11-03-llm-routing-model-cascades)).
The honest tradeoff, also from that literature: cascading adds latency on the
hard cases specifically, because a rejected cheap-model answer means paying
for both calls in sequence
([tianpan.co, "LLM Routing: How to Stop Paying Frontier Model Prices for
Simple Queries"](https://tianpan.co/blog/2025-10-19-llm-routing-production)).
For a background system with no one waiting on the answer (the Mind, memory
extraction, dreaming), that latency cost is close to free — which is exactly
the situation where a cascade is cheapest to adopt.

### Token budgeting for always-on agents

Current guidance converges on budgets enforced at multiple layers
simultaneously — per-request, per-session, per-day, with automatic
termination at the ceiling — because a background agent that "chains model
calls, triggers external APIs, spawns sub-tasks, and runs around the clock
without human approval" can turn a few-hundred-token prompt into tens of
thousands of tokens inside one workflow
([waxell.ai, "AI Agent Token Budget Enforcement"](https://waxell.ai/blog/ai-agent-token-budget-enforcement);
[Portal26, "AI Agent Cost Control"](https://portal26.ai/ai-agent-cost-control-stop-agents-burning-budget/)).
One concrete reference point: a background-tier agent budgeted at "30 calls
per minute, 200 calls per hour, 500K tokens per day" (same source) — roughly
2.5x Marvi's current 200,000/day Mind-only ceiling, for comparison. The
guidance is also explicit that tracking spend after the fact is not the same
as controlling it going forward, and recommends pairing hard caps with
anomaly detection on call-rate and cost spikes that don't correlate with real
user activity ([Ramp, "How to Set Spending Controls for AI
Agents"](https://ramp.com/blog/ai-agent-spending-controls)) — which is
precisely the shape of the `vision_sleep_state` incident this report measured:
a fixed-interval sensor producing a spike in *attempted* calls with no
corresponding change in real activity.

### Debouncing, coalescing, and deduplicating noisy streams

Three distinct mechanisms recur in current material, and Marvi's Mind
currently has none of them upstream of `deliberate()`:

- **Debounce** — collapse a burst of rapid-fire events into one run using a
  sliding window, so a tool or sensor firing repeatedly in quick succession
  produces one decision instead of many
  ([Inngest docs, "Debounce"](https://www.inngest.com/docs/guides/debounce)).
- **Coalescing** — collapse multiple distinct deliveries of what is really
  one logical event (a webhook firing several times while an object
  converges to its final state) into a single agent invocation, at the
  route/event-type level rather than inside the agent
  ([github.com/NousResearch/hermes-agent#20201](https://github.com/NousResearch/hermes-agent/issues/20201)).
- **Deduplication** — before invoking the model, check a persistent
  seen-event store by event id; on a repeat, replay the stored decision
  instead of re-running the model, which matters specifically for LLMs
  because "you cannot treat LLM inference as just another function inside an
  at-least-once pipeline... an LLM might answer differently to the same event
  on successive passes"
  ([tianpan.co, "The Idempotency Crisis: LLM Agents as Event Stream
  Consumers"](https://tianpan.co/blog/2026-04-19-llm-agents-event-stream-idempotency)).

Separately, for the interruption decision itself rather than the plumbing:
current material on proactive-agent notification design frames it as expected
utility (probability the user acts, weighted by the value of acting) against
attention cost (how disruptive the interruption is right now), with a
reported empirical ceiling of roughly 3–5 unsolicited notifications per day
across *all* sources before a user starts tuning an assistant out
([tianpan.co, "Background Agents and the Notification Budget"](https://tianpan.co/blog/2026-05-13-background-agents-notification-budget-attention-economy)).
That reframes the Mind's `cooldown_seconds`/quiet-hours logic
(`policy.py:223-256`) as under-instrumented in one respect: it caps *how
often one source* may sound, but nothing in `policy.py` counts or caps the
*total* number of surfaced things per day across all sources the way this
attention-budget framing suggests it should.

---

## The question: what should sit in front of the Mind's LLM call

Ranked, with the tradeoff of each, against what Half 1 actually found.

**1. Novelty/dedup on the event itself, before the surface ceiling is even
consulted — do this first.** `Mind.tick` currently treats every pending
event as a fresh decision. Nothing in `mind.py` or `policy.py` asks "have I
seen this exact kind of thing, from this exact source, very recently, with
nothing else different about it?" A `vision_sleep_state` transition is a
binary flip (awake/asleep); a run of them in a short window is the same fact
repeated, not new information each time. A cheap dedup/debounce keyed on
`(source, kind)` with a short window — collapsing a burst into the *last*
event in the burst, the way `Inngest`'s debounce or a webhook coalescer would
— catches exactly the shape of the incident measured in §1 even before
today's ceiling fix existed, and it composes with that fix rather than
competing with it: today's fix stops `vision_sleep_state` from ever reaching
the model; a dedup layer stops it from generating 11,447 *events* in the
journal in the first place, which is a separate cost (SQLite writes, the
`pending()` scan on every 2-minute tick) that the ceiling fix doesn't touch.
**Why first for this codebase specifically:** it is the one gap that the
commits from this morning don't close, it requires no model of any size, and
it directly targets the literal largest number in this report (11,447 of
12,135 events, 94.3%, from one sensor).

**2. Keep and extend the surface-ceiling gate that just landed (`_worth_thinking_about`,
`mind.py:37-64`) — verify it, then generalize its shape to §7.** This is
already done for the Mind and is the single highest-leverage fix in the
whole review, by the numbers: it eliminates the code path that produced 90.1%
of all-time Mind token spend. The immediate next step isn't more work on the
Mind, it's recognizing that `remembering.extract()` and `learning.propose()`
(§7) are the same unguarded shape the Mind had until this morning — an
unconditional per-occurrence model call whose own system prompt says the
answer is usually nothing — and giving them an equivalent pre-filter: a cheap
heuristic ("was this turn more than an acknowledgement, did it contain a
first-person statement, a correction, a name, a date, a product") ahead of
`distil.ask`, mirroring `needs_memory()` (`session.py:191-200`), which already
exists in this codebase for exactly this purpose but is only wired to the
memory *reader* (§8), not to extraction or skill proposal.

**3. A cheap local classifier as the escalation gate, where the ceiling table
can't express the judgment.** The surface-ceiling table is a static map from
event *kind* to a maximum surface — it can't express "this particular
`light_changed` event is unusual" versus "this is the fortieth one today."
`presence.py`'s `_judge()` (§9) is the model in this codebase that comes
closest to a genuine classifier-gated escalation: call the model only when a
cheap deterministic check (`disagree(found)`) says the easy cases don't cover
this one. The same shape generalizes to the Mind: a lightweight anomaly/rate
check per `(source, kind)` — "this fired N standard deviations more than its
trailing rate" — sitting between the ceiling check and `_worth_thinking_about`,
so a normally-quiet `device_offline` that suddenly fires ten times in an hour
still gets to ask a model, while a normally-noisy source stays capped even if
it would otherwise clear the ceiling. This is more machinery than #1 or #2 and
should come after them, once it's clear the ceiling table alone isn't
catching the remaining cases.

**4. Tiered escalation / cascade for the calls that do fire.** Once an event
clears the gates above and a call is genuinely warranted, `deliberate()`
currently goes straight to whatever `MARVI_MIND_PROVIDER`/`auxiliary` role
resolves to (`deliberate.py:70,95-97`), with the full `MIND_TOOLS` set
available. A cascade — a first pass with no tools and a much smaller output
cap that can only ever answer `worth_it: false` cheaply, escalating to the
current tool-enabled call only when that first pass says `true` or can't
decide — would cut the cost of the 97.4%-silent outcome further, at the price
of the latency-doubling tradeoff the cascade literature is explicit about
([tianpan.co, "LLM Routing" ](https://tianpan.co/blog/2025-10-19-llm-routing-production)).
For the Mind specifically that tradeoff is nearly free, because nothing is
waiting on the tick's answer — this is worth doing, but it's optimization on
top of a gate, not a replacement for one, and it should wait until #1 and #2
are in and re-measured, since it's solving a smaller residual problem than
either.

**5. A shared token ledger across every path in §2–10.** Not a gate by
itself, but a precondition for knowing whether any of the above worked, or
whether the next incident is happening in a part of the system with no
`journal.sqlite3` equivalent. Given that §7 (remembering + skill proposal) is
now, by this report's own finding, the largest *unmeasured and unguarded*
per-occurrence cost in the codebase, and given that adding one
`journal.record_decision`-shaped row per call is a small change against each
of `distil.ask`'s seven call sites, this is cheap to do alongside #2 rather
than after it.

**What I would do first, for this codebase, given what Half 1 found:** #1
(dedup/debounce on `(source, kind)` before an event is even journaled) and #2
(extend today's ceiling-gate pattern to `remembering.py`/`learning.py`) —
together, before #3 or #4. The reasoning is entirely from the measured data:
today's ceiling fix already addressed the single largest cost (90.1% of
all-time Mind spend, confirmed against 11,447 raw events from one sensor), so
the marginal next dollar is not in making the Mind smarter about *which*
model to call — it's in (a) making sure the same sensor flood doesn't keep
writing 11,447 journal rows a day even though none of them can reach a model
anymore, and (b) closing the one place in the whole review where an
un-gated, always-fires, "usually nothing" model call is still live on every
single conversational turn.
