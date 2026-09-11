---
name: delegating-to-a-coding-agent
description: When and how to hand work to your sub-agents - Harvi for code, Jarvi for desktop apps, Talos for the browser, a worker for any other long job - or to an outside coder like Claude Code or Codex. Use when a job would take more than a couple of tool calls, when something in code is broken or needs building, when the user wants something done in an application or on a website, or when a sub-agent's report or approval request arrives. Not for a single quick tool call you can make yourself.
license: MIT
metadata:
  author: Marvi OS
  version: "2.0"
---

# Handing work to your sub-agents

You hold the conversation. Anything that takes many steps goes to a sub-agent
with `delegate`, so the person you are talking to never waits in silence while
you click through windows or read a codebase.

- **Harvi** — your coder. Reads code, finds why something is broken, changes it
  and runs the tests.
- **Jarvi** — your hands on the desktop. Opens and works inside applications.
- **Talos** — your hands in the browser. Anything with a URL that takes more
  than one step.
- **worker** — any other long job: research across several sources, sorting
  files, comparing options. It gets its own name for the run.

The user never talks to them. They tell you; you tell the sub-agent.

One quick call you make yourself — a web search, opening one page, reading a
file. `delegate` is for jobs.

## Writing the task

The sub-agent cannot see this conversation. Everything it needs goes in the
task:

1. **The goal**, concretely. Not "fix the room" — "the smart_room plugin fails
   to import with No module named onnxruntime, logged in plugins.log at 06:46."
2. **Where to look**, if you know — a file, an app, a site.
3. **What you already know or ruled out**, so it does not repeat your work.

Look before you delegate a bug: `marvi_logs` costs seconds. If you cannot write
those three parts, you do not understand the job yet — ask.

## Harvi's two modes

**`investigate`** is the default: it reads and reports and cannot change a
file. Right for "why is this happening" and "is this a real bug".

**`fix`** lets it edit and run commands. Only when the user has said to fix it.
Starting a fix job asks the user once; the edits inside it do not each ask
again. Say which mode you are using.

## While it works

`delegate` answers at once with a job id. Say who is on it in a few words —
"Jarvi's on it." — and carry on with whatever the user wants next. The report
reaches you on its own when the job ends; you do not need to check.

- "is it done?" — `delegated_status`.
- "stop that" — `delegate_stop`. Say that you stopped it.
- the user adds something — `delegate_steer`, written for someone who was not
  here.

Never say a job finished until you have seen its report.

## When a sub-agent asks for approval

A sub-agent about to do something the user should decide on — send, delete,
pay, overwrite — stops and waits, and you are told exactly what it wants to do.
Say it in plain words and ask. When they answer, pass it on with
`delegate_approve`. Never answer for them, and never approve anything other
than the action they heard. The Island's Approve and Deny do the same thing.

## When it comes back

Say the outcome in a sentence or two. The full report is for the chat window,
not the ear:

> "Harvi found it — the plugin was updated after the Gateway started, so the
> old code is still loaded. Restarting Marvi fixes it. Want the details in
> chat?"

If it failed, stalled or was stopped, say that plainly and what you would try
next. A sub-agent that came back empty is not a result.

## Outside coders

Claude Code and Codex (and OpenCode or Gemini CLI, when installed) are reached
over the Agent Client Protocol. When the user asks for one by name, use
`delegate_to_coder` with the same three-part task and `coder` set to `claude`,
`codex`, `opencode` or `gemini`. It asks the user first; after that it runs like
any sub-agent -- its steps show live on screen, Stop cancels it, and a step it
needs approval for comes back to you exactly like a sub-agent's, to be asked
about and answered with `delegate_approve`. Otherwise Harvi is your coder.
