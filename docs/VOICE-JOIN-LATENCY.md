# Why joining a voice session is sometimes slow

Written 2 September 2026, from this machine's own logs. Two faults were found
and fixed; a third is understood, measured, and deliberately not fixed yet
because the fix has a cost worth deciding with real numbers rather than
guessing. This is the note to read alongside those numbers.

## The short version

| symptom | cause | state |
| --- | --- | --- |
| The agent never joins at all | one fixed room name, and automatic dispatch fires on room *creation* | **fixed** |
| Join is offered, then takes 5-25s to reach listening | the readiness signal said "warm" while the pool was empty | **fixed** |
| A join still occasionally waits for the models | `num_idle_processes=1`, and prewarm costs 4-112s | **open, instrumented** |

## Fixed: the agent that never turned up

The desktop asked the Gateway for a token and always got the room
`marvi-os-local`. Marvi uses automatic dispatch, which means LiveKit sends the
job **when the room is created**. An empty LiveKit room does not disappear at
once -- it lingers for its `empty_timeout`, five minutes by default. Join again
inside that window and the room already exists, so nothing is created, so no
job is dispatched, and the desktop sits connected to a room with nobody in it.
Leaving and rejoining after the timeout is what made it "start working again".

LiveKit's own writing on join latency lists this directly: *use a unique room
name for each user-agent interaction*. The participant identity was already
unique per session. The room was not, and the room is the half dispatch keys
on.

`/livekit/session` now issues `marvi-os-<random>` per session.
`MARVI_LIVEKIT_ROOM` still pins it for anyone who needs a fixed name.

## Fixed: the readiness signal that never went back down

`_state["warm"]` was set to `True` when the first worker process finished
loading its models, and never set back. So from that moment the Gateway
reported *"a warm process is waiting"* forever, including through the whole
time the pool was empty and refilling.

The desktop uses that signal to decide whether Join is worth offering. It was
therefore offering Join at exactly the moments a join would be slowest.

`_pool_is_busy` now reports not-ready as a job takes the process, and the
replacement's own prewarm reports ready when it finishes.

## Open: one warm process, and prewarm is not cheap

This is the part left to decide, and the reason for the new logging.

LiveKit runs each job in its own process and keeps `num_idle_processes` of
them warm. Marvi sets that to **1**, deliberately: this is one person's desktop
holding one conversation at a time, and the default of `ceil(cpu_count)` had
several processes each loading a speech model onto the same 12 GB card.

The consequence is a race. A join takes the warm process; LiveKit starts a
replacement, which begins loading models; if a second join arrives before that
finishes, it gets a **cold** process and waits for the whole load.

From this machine's log, one join in full:

    13:23:24  initializing job runner
    13:23:34  speech models ready in 9.8s     <- prewarm, inside the join
    13:23:34  joined marvi-os-local in 0.5s

The join itself was half a second. The person waited ten.

### What prewarm actually costs

Every completed prewarm recorded on this machine, in order of size:

    4.4s   4.7s   5.7s   9.8s   21.7s   24.5s   26.9s   27.5s
    31.5s  42.0s  65.8s  73.9s  112.4s

That spread is the problem. It is not a constant to design around; the same
configuration produced 5.7s and 25.4s twenty minutes apart, and the largest
figures coincide with the GPU being busy with something else.

The log now breaks it into its parts:

    prewarm: settings 0.2s, vocabulary 0.4s, tts(kokoro) 17.1s,
             stt(parakeet-tdt) 7.9s, vad 0.3s, total 25.9s

and says so out loud when the total passes ten seconds.

### The options, and what each costs

**Raise `num_idle_processes` to 2.** Removes the race outright: there is always
a spare. Costs a second full copy of the speech models resident on the card.
With Kokoro (82M) and Parakeet ONNX that is affordable; with CuteTTS, VoXtream
or the Kyutai recogniser it is two sidecar processes each holding a model, and
on 12 GB that is where it stops being free.

**Make prewarm cheaper.** The breakdown above says where the time goes before
anything is done about it. If TTS is consistently the large half, a lighter
default engine or a lazier voice load is the lever; if it is the recogniser,
the ONNX session build is.

**Leave it at 1 and rely on the honest signal.** The fixed readiness flag means
Join is now held rather than offered during a refill, so the failure becomes
"the button is briefly unavailable" instead of "Marvi took twenty seconds".
That may be enough on a desktop where joins are minutes apart.

No decision yet. The third option is what ships today because it is free and
already correct; the first is one line if the logs say the race is still being
hit in real use.

## What to send after a real session

The lines worth copying out of `%LOCALAPPDATA%\Marvi-OS\logs\agent.log`:

    job <id> starting for room <room>, process already warm | COLD - ...
    prewarm: settings ..., tts(...) ..., stt(...) ..., total ...
    joined <room> in 0.5s, listening - 10.3s from job start (cold process)

The third line is the one that matters: **the seconds from job start, and
whether the process was cold**. A cold join means the pool lost the race and
the fix is capacity. A warm join that is still slow means the time is somewhere
in `session built` / `speech models loaded`, and the fix is elsewhere.

Warnings are emitted on their own when a prewarm passes 10s (`SLOW_PREWARM`) or
a join passes 3s (`SLOW_JOIN`), so neither needs to be hunted for.
