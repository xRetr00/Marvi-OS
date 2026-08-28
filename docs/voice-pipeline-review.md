# Review — the voice pipeline, the prompt, and tool calls

Measured against Marvi's own logs, read against `livekit-agents` 1.6.10 as
installed, and compared with a pinned upstream tool loop and LiveKit's
published guidance.

## What the pipeline actually costs

From `agent.log`, every timed reply on record:

| | median | p90 | max | n |
| --- | --- | --- | --- | --- |
| `llm ttft` | 578 ms | 1,315 ms | 6,150 ms | 141 |
| `tts ttfb` | 346 ms | 612 ms | 2,229 ms | 131 |
| end to end | 1,797 ms | 5,458 ms | 11,636 ms | 73 |
| user stops → Marvi starts | 122 ms | 2,916 ms | 19,677 ms | 96 |

The medians are healthy. The spread is the complaint: a p90 of 5.5 seconds
end-to-end, and a stop-to-start p90 of nearly three seconds against a median of
122 ms, is a pipeline that is usually fast and occasionally absent. People
remember the p90.

## What is right, and should not be touched

**Prewarm is in the right place.** `prewarm()` loads Kokoro, Parakeet and
Silero at worker start, which is exactly what LiveKit provides
`setup_fnc`/`num_idle_processes` for. 6.8 seconds that used to be paid inside
the session is now paid before anyone joins.

**Progressive tool loading is correct and verified.** 13 tools reach the model
on turn one — 8 hand-written for speech, 4 core from the Gateway,
`end_conversation` — and 53 sit behind `tool_search`. I checked for the obvious
failure of this design, two names for one action, and it is already handled:
`SPOKEN_BADLY` drops the Gateway's `room_state`, `room_set_light`,
`memory_recall` and `memory_remember` because hand-written versions exist.
There are no duplicates.

One correction to the comment above `from_gateway`: it claims the full
catalogue is "five thousand tokens of schema". Measured against the live
`/tools`, all 61 tools come to roughly 866 tokens, and the core set to 132. The
deferral saves about 730 tokens, which is not the reason to do it. The reason
is the one the same comment gives second and should give first — selection
accuracy past 30–50 tools. The token figure is wrong by roughly 6× and should
not be the argument.

**Preemptive generation off is right, and for a reason worth writing down.**
Every source says to turn it on; it is on by default. Marvi is the documented
exception: LiveKit discards a speculative generation when the context changes
before the turn is confirmed, and `on_user_turn_completed` changes it on
*every* turn by inserting the recall block. The log recorded the invalidation
on every turn of a real conversation. This is not a race sometimes lost — with
a hook that always mutates context it can never pay off. Keep it off, and keep
the comment, because the next person to read the LiveKit docs will try to turn
it on.

## The largest gap: the silence during a tool call

LiveKit's own latency guidance lists four highest-impact techniques, and one is
tool-call specific: *limit `max_tool_steps`, consolidate external API calls,
and use a "thinking" sound so users aren't waiting in silence.* The general
voice-AI literature says the same thing more strongly — mask tool latency with
a short acknowledgement so the perceived gap goes to near zero.

Marvi does the opposite, deliberately:

> Never say that you are about to use a tool, and never narrate looking
> something up. Say nothing and use it.

That rule is correct and was earned. With 13 tools in the request and no rule
against it, the model narrated and the narration was cut off the moment the
call began — "Let me check what I know about this", spoken, then silence. Two
half-sentences from a real conversation are in the comment above the rule.

But the two positions are only opposed if the *model* is what produces the
filler. It should not be. The industry technique is a **pre-synthesized clip
played by the framework when the tool-call token appears** — deterministic,
never truncated, because it is not part of the generation that the tool call
interrupts.

LiveKit ships this. `RunContext.with_filler(source, delay=, interval=)` is a
general API on every tool context (`voice/events.py:109`), and it fires on
continuous session idle rather than on a guess. **Marvi already uses it — in
exactly one place**, `await_delegated`, the one tool that takes minutes. Every
ordinary tool call, the 200 ms–2 s ones that make up the p90, runs in silence.

The shape that satisfies both: keep the prompt rule, and give `_call` a filler
with a dwell of roughly 600–800 ms so it only speaks when a call is genuinely
slow. Fast calls stay silent, slow ones stop sounding like a dropped line, and
nothing the model generates gets truncated.

## Context grows for the entire session

There is no trimming anywhere in `services/agent/src`. `ChatContext.truncate(max_items=)`
is public in the installed version and unused, and 1.6.10 also carries a
summarizing compaction internally.

For a normal voice agent this barely matters — calls end. Marvi is always-on,
which is the case where it matters most: every turn adds a user message, an
assistant message, any tool call and output, and a fresh ~1,300-character
recall block. LiveKit's first named lever for `llm ttft` is "keep system
instructions concise and trim or summarize older turns", and `llm ttft` is
Marvi's largest single component at a 578 ms median.

This is a plausible explanation for the p90 tail and it is currently untested.
Before changing anything, the measurement is cheap: log context item count and
approximate token count beside each `llm ttft`, and see whether the slow turns
are the late ones. If they are, `truncate` is a two-line fix. If they are not,
the tail is provider variance and trimming would be theatre.

## The prompt

2,426 characters, about 606 tokens. Not bloated, and unusually good on
substance: nearly every rule is traceable to a specific incident, and the
comments record what was observed rather than what was assumed. That is rarer
than it should be and worth keeping.

The weaknesses are form, and one real contradiction.

**LiveKit's prompting guidance asks for structure Marvi does not have.** Their
recommendation is a multi-layered prompt: explicit rules, concrete examples of
the desired output, and a restatement section repeating the core principles.
Marvi's persona is twelve rules in one continuous paragraph, with no headings,
no examples, and new rules appended wherever they were written. A model reading
it gets the content but nothing that marks which rules are load-bearing.

**Two of the vaguest instructions are the two that keep failing.** LiveKit's
guidance is explicit that models do not internalise vague style goals, and
names "be conversational" and "sound natural" as the anti-pattern. Marvi says
"concise" and "speak naturally in short sentences" — the same shape — and the
measured outcome was a single reply of 67.8 seconds. Adding one worked example
of an acceptable answer length would do more than any adjective.

**The length rule and the length cap disagree.** The prompt asks for short
sentences. `VOICE_REPLY_TOKENS = 250` permits, measured, about 68 seconds of
speech. The cap is documented as a backstop for when the prompt does not land —
but a backstop set at a minute of talking is not a backstop for a rule that
means two sentences. One of the two numbers should move, and it should be a
product decision rather than a quiet one: either the prompt states a concrete
length, or the cap comes down to something a listener would recognise as short.

## Tool calls: prior art, LiveKit, and Marvi

The **reference runtime** runs a per-turn guardrail controller
(`agent/tool_guardrails.py`,
854 lines) around every call. It tracks identical calls by signature hash,
counts repeated failures, enforces loop caps, and returns decisions the runtime
turns into synthetic tool results or guidance appended to the real result. Two
pieces are worth stealing conceptually:

- `_tool_failure_recovery_hint` injects *action-oriented* text into the result
  after repeated failures — "this looks like a loop… do not switch to
  text-only replies; keep using tools, but diagnose before retrying", plus
  per-tool advice. It tells the model how to get unstuck rather than only that
  it is stuck.
- `classify_tool_failure` is documented as mirroring the CLI's user-visible
  `[error]` tag *exactly*, so the guardrail and the user can never disagree
  about whether a call failed.

Its effect classification matches Marvi's own conclusion from a different
direction: `NO_EFFECT_TOOL_NAMES` is an allowlist, and "unknown/plugin/MCP
tools stay effect-capable by default" is the same fail-closed rule as
`classify_action` returning `admin` for a verb it does not recognise.

**LiveKit** already provides part of this for free. `_inject_running_tool_calls`
inserts a flagged in-progress pair for each running call so the model cannot
re-issue one that is in flight — the reference's duplicate guard, in the
framework.
`max_tool_steps` defaults to 3 and Marvi does not set it, which is a reasonable
default left unstated.

**Marvi** handles tool results well and tool *sequences* not at all:
`MAX_RESULT_CHARS = 900`, bookkeeping keys like `ok`/`success` stripped so
"ok True" is never read aloud, and the prompt rule that a tool result is
evidence rather than confirmation. That last one does in prose what the
reference does in code.

**I do not recommend building the guardrail.** The whole agent log contains 16
tool-related lines. There is no loop in the evidence, and a 854-line controller
for a problem that has not happened is the kind of thing this project has been
right to refuse elsewhere. Revisit it if tool use becomes common and the logs
show repeats.

## One incident worth knowing about

On 2026-08-25, once in the entire log, the model emitted its own tool-call
markup as spoken content:

```
Right, this is Windows. Let me use the right command.
<|DSML|tool_calls> <|DSML|invoke name="terminal_run"> …
```

Narration, then raw DeepSeek markup instead of an actual tool call. It has not
recurred — one occurrence in the whole file, three days before this review, and
the no-narration rule landed after it. It is recorded here because it names a
failure mode worth a cheap guard: when the model cannot call a tool properly it
may *say* the markup, and a regex stripping provider tool-call syntax from
content before it reaches TTS costs nothing and prevents a listener ever
hearing it.

## Recommended order

1. **Filler on ordinary tool calls** via `with_filler` in `GatewayTools._call`,
   dwell around 600–800 ms. Highest impact on the complaint, uses an API
   already in the codebase, and does not touch the prompt rule that fixed
   truncation.
2. **Measure context growth against `llm ttft`** before trimming anything. Two
   log fields; it either implicates context or exonerates it.
3. **Resolve the length contradiction** — a concrete example in the prompt, a
   lower cap, or both, but stated deliberately.
4. **Give the persona structure** — headings and one worked example for the two
   rules that keep failing. The content stays; only the shape changes.
5. **Strip provider tool-call markup before TTS.** Cheap, and the one thing
   between a model glitch and the user hearing `<|DSML|invoke name=…>`.

Not recommended: a tool-call guardrail controller, until the logs show a loop.
