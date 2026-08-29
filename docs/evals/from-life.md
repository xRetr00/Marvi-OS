# From life

Scores the same failures the scripted suites look for, against what Marvi
actually did. Run `python evals/from_life.py`; add `--days 3` to narrow it.

## Why this exists

Every case in this folder was found by a person reading a log. That works and
it does not scale: the interesting events are spread across four log files in
four formats, most of what matters was never logged at all, and finding a p90
meant a regex over `agent.log`.

Marvi now records what she does as she does it, one JSON object per row, in
`state/observations.jsonl`. This reads it.

## What is recorded

| kind | written when | why it is worth keeping |
| --- | --- | --- |
| `recall` | memory answers a question | the confidence numbers were computed and discarded for months; looked at once, they separated "found something" from "returned five rows anyway" immediately |
| `store` | the worker judges a turn | it ran for weeks keeping 17 of every 25 facts it should have, and an extraction that returns nothing looks exactly like a turn with nothing in it |
| `gate` | a connector offers, or a tool proposes | a regex here silently dropped an exam result, a dentist appointment and a rent bill |
| `tool` | any tool runs, or a search finds nothing | the only honest signal about which tools are missing |
| `reply` | a spoken turn finishes | prompt leaks, monologues and invented memories were all found by hand |

## Reading it

Three numbers matter more than the rest.

**Leak rate.** Any non-zero value is a live bug. It means Marvi spoke part of
her own prompt aloud, and the row holds what she said.

**Weak-recall rate rising over time.** The store drifting away from the
questions being asked. Invisible from inside a conversation.

**Tool searches that found nothing.** The answer to "which tools should we
add", and the only place it is written down. A model that searches for
`spotify` twice a week is telling you something no roadmap will.

## What it will not tell you

It scores what happened, so it is silent about what never gets tried. A tool
nobody reaches for looks the same as a tool that works perfectly; a question
nobody asks looks the same as one memory answers well. The scripted suites
cover that ground, and neither replaces the other.

It is also worth nothing after an hour. Run it after a week.

## Privacy

Local, in Marvi's own state directory, never sent anywhere — the same contract
as the memory store it describes. Text is capped at 400 characters per field
and passed through the same redactor as the logs, so a credential spoken aloud
does not end up in an eval file. Switch it off with `MARVI_OBSERVATIONS=off`.
