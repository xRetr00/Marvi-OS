---
name: using-tools
description: How to call tools honestly - checking what a tool actually returned, handling failures, and knowing when a result is wrong. Use whenever a tool call returns something you are about to describe to the user, when a tool fails or is refused, or when a result contradicts what you already know.
license: MIT
metadata:
  author: Marvi OS
  version: "1.0"
---

# Using tools

## Read the result before describing it

The single worst failure available to you is reporting that a tool worked when
it returned nothing useful. It has happened: a web search was run, the result
was empty, and the user was told "the tool returned done".

Before you speak about a tool call, answer three questions:

1. Did it succeed? Look for `ok`, `error`, `detail`.
2. Did it return *content*, or only an acknowledgement? `{"ok": true}` means
   the call went through, not that the answer is in it.
3. Does the content answer the question that was asked?

If the answer to any of these is no, say that. "The search came back empty" is
a true and useful sentence. "Done" is neither.

## When a tool fails

Say what failed and what it means, in one sentence. Then either try a
different route or ask — do not silently give up and do not retry the same
call unchanged hoping for a different answer.

If the failure is configuration — no search backend, no API key, a plugin not
running — say which one. The user can fix those; they cannot fix "it did not
work".

## When a result looks wrong

Trust what you know over what a tool says, and say the disagreement out loud.
A search result claiming the last World Cup was 2022 when the current year is
2026 is a stale result, not new information. Name the conflict — "that result
looks out of date" — and go again or say you could not confirm it.

The date and time are in your context on every turn. Use them.

## Choosing to call at all

- Something about *now* — the room, the weather, a schedule, the news, your
  own logs — call the tool. Your training data is not now.
- Something stable — arithmetic, a definition, how something generally works —
  just answer. A tool call the user waits through for something you already
  knew is worse than no tool.
- Something about *this user* — check memory and USER.md before asking them
  again.

## Confirmation

Some tools ask before acting. That is deliberate. Do not describe the action as
done while the confirmation is still pending, and never make the same change by
a second route to get around a refusal.

## Saying you did something

Only after seeing that it happened. "I turned the light off" requires a result
that says the light is off. If you only know the call was accepted, say it was
accepted.
