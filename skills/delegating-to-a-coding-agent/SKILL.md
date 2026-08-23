---
name: delegating-to-a-coding-agent
description: When and how to hand a coding job to Claude Code or Codex instead of doing it yourself. Use when you find a bug in Marvi, when the user describes something broken in code, when a fix would mean editing files, or when they ask you to build, refactor, investigate or test something in a codebase.
license: MIT
metadata:
  author: Marvi OS
  version: "1.0"
---

# Delegating to a coding agent

Two coding agents are installed on this machine, and they are better at this
than you are. You are the one holding the conversation; they are the ones that
read a codebase properly and leave their work in git.

- **claude** — reading unfamiliar code and explaining what is wrong
- **codex** — making a contained change and running the tests

## Ask first, always

`delegate_to_coder` needs confirmation, and that is the point, not an obstacle.
The user decides whether an agent runs against their source code.

Offer it in one sentence, with what you would ask it to do:

> "The room plugin failed to import at startup. Want me to put Claude Code on
> it?"

Not "shall I delegate this task". Say what is wrong and what you would ask.

If they say no, that is the end of it. Do not offer again for the same thing
in the same conversation.

## Which mode

**`investigate`** is the default and is right almost always. The agent reads
and reports; it cannot change a file. Use it for "why is this happening",
"where does this come from", "is this a real bug".

**`fix`** lets it edit. Only when the user has said to fix it, in those words
or clearly enough. Say which mode you are using when you ask.

## Writing the task

The agent cannot see this conversation. Everything it needs goes in the task.

A good one has three parts:

1. **The symptom**, concretely. Not "the room is broken" — "the smart_room
   plugin fails to import with No module named onnxruntime, logged in
   plugins.log at 06:46."
2. **Where to look**, if you know. A file, a service, a log.
3. **What you already ruled out**, so it does not repeat your work.

Look before you delegate. `marvi_logs` costs you seconds and makes the
difference between a task worth running and one that wastes ten minutes. See
`diagnose-myself`.

## While it runs

It returns a job id immediately and takes minutes.

**Call `await_delegated` with that id straight away.** It does not block: it
answers at once so you can keep talking, and the result arrives on its own when
the job finishes. You do not have to remember to check, and the user does not
have to ask.

> "Claude Code is on it — job 3f2a. What else were we doing?"

Then carry on. Answer whatever they ask next; the job is still running. When it
finishes you will be handed the outcome mid-conversation — read the room before
interrupting with it, but do not sit on it.

`delegated_status` is the other way: it checks once, right now, and returns
whatever the state is. Use it when the user asks "is that done yet?" and you
are not already waiting.

If the user changes their mind — "forget it", "stop that" — you can cancel:
`get_running_tasks` lists what is running and `cancel_task` stops one. Say that
you stopped it.

Never claim it finished until you have seen a result saying so.

## When it comes back

Say the outcome in a sentence or two, out loud. The full output is long and is
for the chat window, not the ear:

> "It found it — the plugin was updated after the Gateway started, so the old
> code is still loaded. Restarting Marvi fixes it. Want the details in chat?"

If it failed or timed out, say that plainly and what you would try next. A
coding agent that came back empty is not a fix.

## What not to delegate

- Anything you can answer by reading a log. Ten minutes of an agent to learn
  what one search would have told you is a bad trade.
- Anything outside the workspace root. It will refuse, and correctly.
- A vague task. If you cannot write the three parts above, you do not
  understand the problem well enough to hand it over yet — say so and ask.
