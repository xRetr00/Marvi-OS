# Who owns a Marvi process, and how everything stops

Written 3 September 2026, after a day in which the Gateway was found running
with no desktop behind it, three Python processes deep, refusing the Agent its
provider credentials 285 times and answering every memory question with
nothing.

Implemented 3 September 2026. What follows is the design and then, at the end,
what shipped and what turned out to be unnecessary.

## The fault

**Ownership is inferred, and every inference is wrong in some case.**

Nothing records who started what. Instead, at launch, `reclaimPort` asks one
question of whoever holds port 8765 -- *is its parent process still alive?* --
and acts on the answer:

    parent alive  -> "held by another running Marvi"  -> leave it, and adopt it
    parent dead   -> abandoned                        -> kill it

Both branches fail:

| Situation | What is inferred | What is true |
| --- | --- | --- |
| The parent's PID was reused by an unrelated process | owned, adopt it | abandoned |
| The old desktop is still shutting down | owned, adopt it | it is about to die |
| The Gateway was started from a shell or by a script | owned by *something* | owned by nobody |
| Machine rebooted; a PID from before the reboot is live again | owned | meaningless |
| No desktop at all, but a live process somewhere in the chain | owned | orphaned |

The last row is what happened. And the moment a Gateway is *adopted* rather
than started, everything it was configured with at its own launch is stale:
the local token (285 refusals and dead voice sessions), the provider settings,
the model choice, the log destination, the plugin roots.

`MARVI_PARENT_PID` is the same inference from the other side. The child
watchdog exits when that PID stops existing -- which is right when the parent
died and wrong when the PID was recycled, and silent either way.

So the bug is not in `reclaimPort`. The bug is that ownership is a question
being *asked about the operating system* when it should be a fact *written
down at launch*.

## The fix: declare ownership, never infer it

One file, written by the desktop before any child starts:

    %LOCALAPPDATA%\Marvi-OS\state\runtime.json

    {
      "launch_id":  "9f2c...",        random, one per launch
      "boot_id":    "2026-09-02T18:04:11Z",   the machine's boot time
      "desktop": { "pid": 18972, "started_at": "...Z" },
      "children": {
        "gateway": { "pid": 16356, "started_at": "...Z", "port": 8765 },
        "agent":   { "pid": 24880, "started_at": "...Z" }
      }
    }

Every child is handed `MARVI_LAUNCH_ID` in its environment. Three rules follow,
and between them they replace every inference above.

### 1. A process is identified by PID *and* start time

`isAlive(pid)` is not an identity check; PIDs are recycled within minutes on a
busy Windows machine. `describeProcess` already reads the command line and the
parent -- it gains the creation time, and every comparison becomes:

    same process  ==  same pid  AND  same creation time  AND  command line matches

This alone closes the PID-reuse hole in `reclaimPort`, `killStrays` and the
parent watchdogs, and it is independently correct, so it ships first.

### 2. `boot_id` makes stale records unreadable rather than misleading

A `runtime.json` written before the last reboot describes PIDs that mean
nothing. Recording the machine's boot time and comparing it on read turns that
from a dangerous record into an absent one.

### 3. A child exits when it is no longer the current launch

The watchdog stops asking "is my parent alive" and starts asking two questions
it can actually answer:

* has `runtime.json` gone? -> the desktop shut down cleanly. Exit.
* does its `launch_id` differ from mine? -> a newer launch owns this machine.
  Exit.

The parent-PID check stays as a third condition, now with identity
verification, for the case where the desktop is killed without tidying.

This is what makes adoption impossible: a Gateway from a previous launch does
not need to be found and killed, because it removes itself the moment a new
launch writes a new id. Killing it at startup becomes the fallback for a
process that is wedged, not the mechanism.

## What each lifecycle event becomes

**Start.** Read `runtime.json`. If it exists and matches this boot, stop every
recorded child by verified identity, then write a new record with a new
`launch_id` before spawning anything. Nothing is ever adopted.

**Restart.** Identical to Start. The previous launch's children exit on their
own when they see the new id, and are killed only if they do not.

**Shutdown.** Delete `runtime.json` first, then stop the children. If the
desktop dies before finishing, the children have already seen the file go and
are exiting anyway.

**Update.** The updater waits for the desktop to exit, and every child watches
the desktop's PID as its third condition -- so they stand down on their own
before any file is replaced. No change to the updater was needed; see the note
at the end.

**Crash of the desktop.** `runtime.json` stays, but the desktop entry's pid and
creation time no longer resolve to a live process. Children exit on the third
condition, and the next launch finds a stale record it can safely clean.

## What this fixes, concretely

* The Agent is never handed a Gateway from a different launch, so
  `MARVI_LOCAL_TOKEN` cannot mismatch. The on-disk token fallback added on
  2 September stops being load-bearing and becomes a belt to the braces.
* A Gateway with stale provider settings, a stale model choice or a stale log
  path cannot outlive the launch that configured it.
* `killStrays` and `reclaimPort` stop being the primary mechanism and become
  the recovery path, which is the only role a heuristic should have.
* "Is Marvi running?" gets an answer that is a fact rather than a guess, which
  the installer, the updater and Doctor all currently re-derive differently.

## What shipped

1. **Identity verification.** `describeProcess` now reads the creation time,
   and `isSameProcess(pid, record)` compares number, creation time and command
   line. `reclaimPort` uses it, so an abandoned Gateway whose parent's PID has
   been reused no longer reads as "another running Marvi".
2. **`ownership.ts`.** `runtime.json` with a `launch_id`, the machine's boot
   time, and every child by PID and creation time. Written atomically -- see
   below -- claimed before the first spawn, cleared before the children on
   shutdown. `MARVI_LAUNCH_ID` goes to every child.
3. **Child watchdogs.** `marvi_gateway/parent.py` and the Agent's
   `_watch_parent` each gained the same three conditions: the record names a
   different launch, the record is gone, or the parent PID no longer exists.
4. **Startup.** `ownership.stopPrevious` runs before `killStrays` and
   `reclaimPort`, stopping the previous launch's children by recorded identity.
   The two sweeps remain as the fallback for a process that is wedged or
   belongs to another checkout.

### The race this nearly shipped with

The record is rewritten every time a child starts, and every child reads it on
a timer. The first version returned "no record" for both an absent file and an
unparseable one -- so a reader landing mid-write would have concluded the
desktop had shut down, and **every child would have exited at once**. A test
written to assert the opposite caught it.

Two defences, because the cost of getting it wrong is the whole stack:

* the writer renames a temporary file into place, which is atomic
* the reader tells `GONE` from `UNREADABLE` and only acts on the first, and
  requires the condition twice in a row before standing down

### Step 5 turned out to be unnecessary

The plan had the updater bump the launch id before replacing files. It does not
need to: the updater already waits for the desktop to exit, and every child
watches the desktop's PID as its third condition. Once the desktop is gone the
children stand down whether or not the record was touched. Adding a Rust change
for a case already covered would have been motion rather than work.

## Still to do by hand

The startup path is the part that changes what happens at launch, and it wants
a run on a real machine rather than a test: launch, relaunch while running,
kill the desktop and relaunch, and reboot with services set to autostart.

## What is deliberately not proposed

**A lock file as the sole mechanism.** A lock says "somebody is running" and
not "who", and the failure here was adopting the wrong owner rather than
running twice.

**Killing anything that matches `marvi_gateway` on the machine.** Two checkouts
is a supported thing to do; `killStrays` is already scoped to an install root
and should stay that way.

**A supervisor process.** It would be a fourth thing that can be orphaned.
