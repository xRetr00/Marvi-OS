---
name: remembering
description: What to write to memory, how to search it, and how to treat what comes back. Use when the user tells you something worth keeping, when you are about to ask something you may already know, when a recalled note contradicts what they just said, or when they ask what you remember. Not for standing facts about the person themselves, which is knowing-the-user, and not for what merely happened this session.
license: MIT
metadata:
  author: Marvi OS
  version: "1.0"
---

# Remembering

Six tools: `memory_remember`, `memory_search`, `memory_forget`, `memory_link`,
`memory_neighbours`, `memory_reflect`. Most turns need none of them — a few
relevant notes are already in your prompt before you start.

## What is worth keeping

Write down what will still be true and still be useful next week:

- decisions and their reasons — "we run recognition on the CPU so it stops
  competing with speech for the card"
- specifics that are annoying to rediscover — a port, a path, a name
- what happened, when it matters later — "the room plugin failed to load on
  the twenty-third"

Do not write:

- what the code or the logs already record. If it can be looked up, look it up.
- something that is only true today
- a summary of the conversation you just had
- anything you inferred rather than were told, unless you say it was inferred

**A standing fact about the person is not memory.** Their name, their work,
how they want to be addressed — those go in USER.md, which is in every prompt.
Memory is searched and only surfaces when a turn happens to match. See
`knowing-the-user`.

## Writing one

One fact per note, with enough context to be read cold in three months.
"Port 17842" is useless later; "the room sidecar's RPC port is 17842" is not.

Convert relative dates. "Last Tuesday" means nothing to the note; the date
does.

## Searching

Search before asking. Being told the same thing twice is the fastest way to
seem like you were not listening.

Search with the words the user used, not with the words you would have used.
`memory_neighbours` finds what a note is connected to; `memory_link` makes
that connection when you notice two notes are about the same thing.

## Reading what comes back

**A note is what was true when it was written.** It is not evidence about now.
If a note says the recogniser runs on the card and the setting says otherwise,
the setting wins and the note is stale — say so and fix it.

Do not repeat notes back unprompted. Using what you remember looks like
listening; reciting it looks like a filing cabinet.

## Being wrong

If the user corrects something you remembered, `memory_forget` it and write
the correction. Two contradicting notes are worse than none, because the next
search will surface whichever one matches the words better.
