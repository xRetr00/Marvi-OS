---
name: diagnose-myself
description: Find out why part of Marvi is not working by reading her own logs. Use when the user says something of yours is broken, missing, offline, silent, slow, or not connected - the room, vision, the voice session, the wake word, a plugin, a model, a provider - or when a status light is red and they ask why.
license: MIT
metadata:
  author: Marvi OS
  version: "1.0"
---

# Diagnosing yourself

You can read your own logs with `marvi_logs`. Do that before answering. A
guess that sounds right is worse than "let me look", because the user cannot
tell the two apart.

## Which log

| Log | What is in it |
| --- | --- |
| `errors` | Everything at WARNING and above, from every service. **Start here.** |
| `gateway` | HTTP requests, tool calls, startup |
| `agent` | The voice worker: recognition, speech, turn-taking, tool calls in a session |
| `voice` | Recogniser and synthesiser loading, device choice, timings |
| `livekit` | The media server. Very noisy; only useful for a room that will not join |
| `plugins` | Plugin loading, updates, dependency installs |
| `mind` | Background thinking, curiosity, initiative |
| `providers` | Model calls, rate limits, authentication |
| `chat` | Typed conversation |
| `installer` | Model and component downloads |
| `presence` | Who the room thinks is there, with every sensor reading behind it |

## How to look

Start narrow. `marvi_logs` takes `contains`, and a name plus a search term
beats reading forty lines of something else:

- `marvi_logs(name="errors", lines=30)` — what has gone wrong recently
- `marvi_logs(name="plugins", contains="failed")` — a plugin that did not load
- `marvi_logs(name="agent", contains="stt:")` — what you actually heard
- `marvi_logs(name="voice", contains="ready")` — which device the models are on
- `marvi_logs(name="presence", contains="judged")` — the times the sensors
  disagreed and a model had to weigh them

## Reading what you find

**A timestamp before the current session is history, not a fault.** Check the
time against the current date before reporting anything as a live problem.

**Distinguish the symptom from the cause.** "sidecar not connected" is a
symptom; "plugin failed to load" in `plugins` a few minutes earlier is the
cause. Keep looking one level up until the line explains itself.

**Some noise is permanent.** `CPU monitoring unsupported on current platform`
from LiveKit and `error reading data channel ... User Initiated Abort` when a
session ends are both normal. Do not report them as problems.

## Known shapes

- **A plugin is installed but not running.** Its code was imported when the
  Gateway started, and an update since then is not live. The fix is restarting
  Marvi. Say so plainly rather than describing the plugin as broken.
- **A provider returns 401.** A key is missing or expired. Name the provider;
  never read a key back, and never put one in a reply.
- **The room or vision is offline.** Vision runs inside the room sidecar, so
  the room is the thing to check; vision cannot be up on its own.
- **The voice session says no agent joined.** Check `agent` for whether the
  worker registered, then `livekit` for whether the room accepted it.

## Reporting it

Say what you looked at, what you found, and what would fix it. One or two
sentences by voice; the user can ask for more. If the logs do not explain it,
say that too — "the plugin log shows nothing since this morning" is a real
answer and an invented cause is not.
