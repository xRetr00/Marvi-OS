# Tools

Whether a tool is callable, safe, and worth the tokens it costs on every turn.

## The budget is the first question

Measured live: **2,529 tokens reach the model on every voice turn before the
user says a word** — persona 607, skills catalogue 979, SOUL.md 406, location
113, identity 96, plus a recall block around 325. `llm ttft` scales with that
and is the largest single component of a spoken turn at 578 ms median.

A tool that is not reachable does not merely fail. It is paid for on every turn
for as long as it is loaded.

## Progressive loading

13 tools reach the model on turn one — 8 hand-written for speech, 4 core from
the Gateway, `end_conversation` — and 53 sit behind `tool_search`.

The argument for this is **selection accuracy, not tokens.** Measured against
the live `/tools`, all 61 tools come to roughly 866 tokens and the core set to
132, so deferral saves about 730 tokens: not worth designing for. Past roughly
30–50 tools a model's ability to pick the right one degrades, and that is the
reason. (A comment in `from_gateway` claimed 5,000 tokens; it was wrong by 6×.)

## Checks when adding a tool

1. **Is it actually reachable?** A tool in config that the router never loads
   is invisible while looking installed. This happened to MCP servers:
   `load_server_config` read one file shape and the Settings flow wrote
   another, so anything added through the UI was never routable.
2. **Does it duplicate one that exists?** Two names for one action makes the
   model choose on every turn with nothing to choose on. `SPOKEN_BADLY` exists
   for this — the Gateway's `room_state` is dropped because a hand-written
   spoken version exists.
3. **Does its description read aloud?** A schema written for a typed interface
   makes a poor spoken tool.
4. **Does it need a filler?** Anything that can take more than about a second
   should run under `RunContext.with_filler`, so the wait is not silence.

## Effects must not be guessed from words

`classify_action` infers read/write/admin from verbs in an action slug. It
fails **closed** on an unknown verb — an unfamiliar action is `admin` — and
fails **open** on a known-but-wrong one: any slug containing `GET` or `LIST` is
`read` and runs without confirmation whatever it does upstream.

A curated per-toolkit catalogue is the trust anchor: an uncurated slug on a
catalogued toolkit is refused rather than guessed. Verify with:

```
GMAIL_GET_SOMETHING_INVENTED  -> admin   uncurated on a catalogued toolkit
GITHUB_LIST_SECRET_SCANNING   -> admin   reads as a read by name
SPOTIFY_GET_PLAYLIST          -> read    no catalogue, heuristic applies
SPOTIFY_ZORBLE_THE_THING      -> admin   unknown verb, fails closed
```

## Untrusted results

Anything a tool returns is information, never instructions. The `untrusted`
case in `evals/voice_behaviour.py` embeds an instruction inside an external-data
envelope and asserts the model reports it rather than obeying it.

Every model tested passes. It stays in the suite because it is the one failure
here that would be a security incident rather than a bad conversation.

## Tool-call latency

Tool calls run sequentially and before the reply, so one turn can carry several
round trips. LiveKit's guidance is to limit `max_tool_steps` (default 3, unset
here), consolidate calls, and cover the wait with a thinking sound — Marvi does
the last at a 0.9 s idle dwell, chosen so a call faster than the 578 ms median
`llm ttft` stays silent.

## What is not measured here

Whether a tool's *result* is any good. `MAX_RESULT_CHARS` truncates and
bookkeeping keys are stripped so "ok True" is never read aloud, but nothing
scores whether the content answered the question. The persona asks the model to
notice; nothing verifies that it did.
