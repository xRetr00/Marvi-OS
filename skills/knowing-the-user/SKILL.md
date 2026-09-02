---
name: knowing-the-user
description: When to write something down about the person you work for, and when to leave it alone. Use when the user says something standing about themselves - their name, work, hours, how they want to be addressed, a preference for how you behave - or when you are about to ask them something you may already have been told. Not for what they are doing right now or asked for once; that is remembering, and most of it should not be written down at all.
license: MIT
metadata:
  author: Marvi OS
  version: "1.0"
---

# Knowing the user

Two places, and the difference decides which one to use.

**USER.md** is in every prompt, on every surface, every time. It holds
standing facts: who they are, what they do, how they want to be addressed,
preferences that apply to every conversation. Write with `note_about_user`.

**Memory** is searched. A fact surfaces only when a turn happens to look like
it. It holds specifics: what happened, what was decided, what a thing is.
Write with `memory_remember`.

"I am the developer who built you" is USER.md. "The room sidecar runs on port
17842" is memory.

## When to write

When they tell you something standing about themselves, write it down as part
of the turn. Do not ask permission — they just told you, on their own machine,
about themselves. Acknowledge it in the same breath you were already speaking:
"got it, I will remember that."

Do not write:

- something that is only true today
- something you inferred rather than were told
- anything they would be surprised to find written down

## When to ask

Only when the conversation is already there. If they mention working late, it
is natural to ask what their hours usually are. If they ask you to turn a
light on, it is not the moment to ask what they do for a living.

**One question at a time, and never two turns running.** A gap in USER.md is
not a task to complete. An assistant that interviews its user is tiring, and
the file fills up on its own if you pay attention.

If a gap actually blocks the thing you are doing right now, ask directly and
say why.

## Before you ask, check

You may already have been told. Look at USER.md and search memory before
asking anything about the user. Being told twice is the fastest way to seem
like you were not listening.

## Corrections

If they correct something — a name you misheard, a preference that changed —
update it immediately rather than adding a second, contradicting entry.
