# Phase 10 — Logging, Doctor, and Staying Up

**Status:** planned
**Depends on:** Phase 9 (providers), Phase 7 (the Windows release)
**Feeds:** Phase 11 (setup), which is built on this phase's remediation engine

## Why this phase exists

Phase 9 ended with a bug report worth quoting, because it is the whole
justification: *"the voice stack is not working, the Gateway did not start, and
the UI shows nothing useful."*

Three services had failed. Every one of them died into `stdio: 'ignore'`, so the
reason went nowhere. The shell showed a connecting animation. There was no log
to read, no state to inspect, and no way to tell "uv is not installed" from
"port 8765 is taken" from "the Python imports are broken" — three completely
different problems that produced one identical symptom.

**A local-first assistant fails on someone else's machine, without a developer
present.** That is the constraint this phase is built around. Marvi cannot ask
for a stack trace; it has to already have one, and where it can, it should fix
the problem itself.

The immediate breakage is fixed (a supervisor that captures output, notices
exits, and reports the reason). This phase turns that into a property of the
whole system.

## 1. Logging — one file per subsystem

A single merged log is unreadable within a day: the voice path alone writes more
than everything else combined, and a room event gets buried under audio frames.
So the log directory is **split by subsystem**, under
`%LOCALAPPDATA%\Marvi OS\logs`:

| File | What goes in it |
|---|---|
| `gateway.log` | HTTP, tool router, confirmations, journal, mind ticks |
| `providers.log` | every model call: provider, model, tokens, cache hits, cooldowns, failover |
| `voice.log` | the agent worker, LiveKit session, STT/TTS, turn detection |
| `vision.log` | camera, face recognition, visitor decisions |
| `room.log` | sidecar RPC, device actions, sleep-mode refusals |
| `desktop.log` | the Electron shell: window lifecycle, IPC, service supervision |
| `setup.log` | installs, downloads, verification, self-healing actions |
| `errors.log` | **everything at WARNING and above, from every subsystem** |

`errors.log` is the point of the split. Each file answers "what was this
subsystem doing"; `errors.log` answers "what went wrong", which is the question
someone actually has. It is the first file to open and usually the only one.

Rotation per file, size-capped, so a week of running does not fill a disk.

Two rules that are easy to get wrong, and both get a test that reads the written
file rather than trusting the call sites:

- **Credentials never reach a log.** Provider keys, OAuth access and refresh
  tokens, account contents. The masking helper from the settings surface applies
  here, enforced by planting a secret and grepping every file for it.
- **Untrusted content stays labelled in the log too.** An email body in a log
  line is still an email body. If someone later pastes a log into a model, an
  unlabelled injection payload is exactly as dangerous there as it was live.

## 2. Doctor — part of Marvi, not a script beside it

**Doctor lives inside Marvi.** It is a module in the Gateway package and a page
in the desktop app — not a PowerShell script in `scripts/`. The distinction
matters: a separate script is a second implementation of the same knowledge, and
the second implementation is always the one that drifts. Marvi's own checks and
Marvi's own remedies come from one place.

### What it checks

Every check answers three things: **is it right, why not, and what fixes it.**

| Area | Checks |
|---|---|
| Dependencies | `uv` present and runnable; Python project synced; the desktop's node modules; `git` for the updater; `hf` for model downloads |
| Models | voice STT/TTS present, correct size and hash against `config/voice-models.json`; vision `buffalo_l` present |
| Binaries | LiveKit server present and matching the version in `config/runtime.json` |
| Configuration | `runtime.json` parses; `providers.env` readable; identity files within the token budget; a bad value clamped rather than obeyed |
| Environment | at least one provider configured **and reachable**; OAuth client IDs present for connected plans; token store readable by this Windows account |
| Ports | Gateway port free or answering as Marvi; LiveKit port |
| Storage | journal, memory and chat databases writable and not corrupt; disk space for models |
| Permissions | microphone and camera at the OS level — no amount of retrying fixes a denied permission |
| Services | each supervised process, its state, and its last output |

### Self-healing — and the line it does not cross

Each finding carries a **remedy**, and every remedy is one of three kinds:

- **Automatic.** Safe, reversible, and obviously what the user wants. Create a
  missing directory. Re-read a config file. Clear a stale cooldown. Restart a
  crashed service. Re-download a model whose hash does not match. These run on
  their own and are written to `setup.log`.
- **One click.** Correct but consequential enough to deserve a decision:
  `uv sync` after a pull, downloading several gigabytes of models, freeing a
  port by stopping another process. Doctor shows the exact action and does it
  when the user says so.
- **Yours to do.** Marvi genuinely cannot: install `uv`, grant a microphone
  permission, free disk space, get an API key. Here Doctor's job is to be
  *specific* — the exact command, the exact Windows settings page, the exact
  URL. "Microphone permission denied" is a bad message; "Settings → Privacy →
  Microphone → allow desktop apps, then reopen Marvi" is a useful one.

The rule separating automatic from one-click: **anything that spends money,
takes real time, downloads at scale, or touches another process is a decision,
not a repair.**

### Copy diagnostics

One button producing one redacted block: versions, every check result, recent
`errors.log` lines, and the last output from each service. This is what makes a
bug report useful, and it is what the user pastes when they ask for help.

## 3. Resilience — failures that are already handled

Some of this exists and should be named rather than rebuilt. Provider cooldown
and failover landed in Phase 9; the service supervisor landed with this phase's
first fix. What is missing:

- **Every long-lived connection reconnects.** The room sidecar, LiveKit, and MCP
  servers each need a documented reconnect policy. Today a dropped sidecar is a
  dead tool until restart.
- **A failed sub-system degrades rather than cascades.** No vision must not stop
  voice. No provider must not stop the room tools — a light switch does not need
  a model.
- **Nothing retries an unrepeatable action.** Retry is safe for reads and unsafe
  for sends. The external-write idempotency from Phase 5 is the boundary:
  **never auto-retry a `spec.external` tool.**

## 4. Retry — bounded, and only where it is safe

One helper, used everywhere, rather than a different `for` loop per call site:

- exponential backoff with jitter, because synchronised retries from several
  subsystems are their own outage;
- a cap on attempts *and* on total elapsed time;
- retry only idempotent operations — reads, health checks, reconnects;
- honour `Retry-After` rather than guessing (already true for providers);
- **surface the failure after the last attempt.** A retry that ends in silence
  is worse than the original error, because now there is a delay too.

## Work breakdown

**Step 1 — the logging module.** Per-subsystem files, rotation, the `errors.log`
fan-in, and the redaction test that greps every written file for a planted
secret.

**Step 2 — every subsystem onto it**, including the Electron shell, whose
supervisor tail becomes `desktop.log` rather than only living in memory.

**Step 3 — checks as a library.** `marvi_gateway/doctor/` — each check a
function returning status, reason, and a typed remedy. Pure and testable; no
printing, no HTTP.

**Step 4 — the remedy engine.** Executes automatic and one-click remedies,
audits each one, and refuses anything marked "yours to do". Phase 11's installer
is built on this.

**Step 5 — the Doctor page**, grouped by area, worst first, with Fix buttons and
Copy diagnostics.

**Step 6 — the retry helper**, and converting existing ad-hoc retries onto it,
with the guard that refuses external writes.

**Step 7 — reconnect policies** for the sidecar, LiveKit, and MCP.

**Step 8 — degradation tests.** Kill each dependency in turn; assert the rest
still works and says what is wrong.

**Step 9 — a crash breadcrumb.** On an unhandled exception, write what happened
before exiting, so the next launch can say "Marvi stopped unexpectedly last
time" and show it.

## Acceptance evidence

- Each of the three original failures — `uv` missing, port taken, broken imports
  — produces a **different, correct** message and a **different, correct**
  remedy.
- Log files exist per subsystem after a clean run, and `errors.log` contains
  the warnings from all of them.
- No key, token, or account content appears in any log file, proven by grepping
  the files.
- Doctor detects a deliberately corrupted model file and re-downloads it without
  being asked.
- Doctor detects a denied microphone permission and does **not** try to fix it,
  naming the exact settings page instead.
- Killing the Gateway mid-session leaves the shell responsive and honest;
  restarting recovers without restarting the app.
- Killing the room sidecar degrades room tools only. Voice keeps working.
- An external write is never retried automatically, proven by a test.
- Copy diagnostics produces a block containing nothing secret.

## Open questions

- **How much log is too much?** An always-on assistant writing debug lines all
  day is a disk problem. Default level and per-file rotation size need a real
  decision, not a guess.
- **Does Doctor run on startup, or on demand?** Leaning toward a fast subset
  automatically — enough to catch the "nothing works" case — and the full sweep
  when asked, since hashing gigabytes of models is not a startup activity.
- **Crash reports stay local.** Marvi is local-first, so nothing uploads. The
  deliverable is a block the user chooses to send.
