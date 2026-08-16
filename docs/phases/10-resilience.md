# Phase 10 — Logging, Doctor, and Staying Up

**Status:** planned
**Depends on:** Phase 9 (providers), Phase 7 (the Windows release)

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
for a stack trace; it has to already have one.

The immediate breakage is fixed (a supervisor that captures output, notices
exits, and reports the reason). This phase turns that into a property of the
whole system rather than one repair.

## The four things, and what each one actually means

### 1. Logging — a file that exists before anything goes wrong

Not `print`, and not only on the console — a rotating file per service under
`%LOCALAPPDATA%\Marvi OS\logs`, written from the moment the process starts.

The requirement that shapes it: **the user must be able to send one file.** So
one place, size-capped, with the Gateway, agent, and shell interleaved by
timestamp rather than scattered across three formats.

Two rules that are easy to get wrong:

- **Credentials never reach a log.** Provider keys, OAuth tokens, and account
  contents. There is already a masking helper for the settings surface; logging
  needs the same discipline, enforced by a test that greps the written file
  rather than trusting the call sites.
- **Untrusted content stays labelled in the log too.** An email body in a log
  line is still an email body; if someone pastes a log into a model later, an
  unlabelled injection payload is exactly as dangerous there.

Levels matter less than a redaction test does.

### 2. Doctor — the page that answers "why is it broken"

A page, and the same checks runnable from a script when the shell itself will
not start. Each check reports pass, warn, or fail **with the fix**, not just the
state:

| Check | Failure the user actually hits |
|---|---|
| `uv` present and runnable | not installed, or not on the PATH a GUI app inherits |
| Python project synced | `uv sync` never ran after a pull |
| Gateway port free / answering | something else took 8765 |
| LiveKit binary present, version matches the manifest | a partial install |
| At least one provider configured and reachable | no key, dead key, dead local server |
| Identity files within budget | silently truncated |
| Journal, memory, chat DBs writable | disk full, or a locked file |
| Token store readable | written under a different Windows account |
| Microphone and camera permission | denied at the OS level, which no amount of retrying fixes |

Doctor is the deliverable that makes a bug report useful: **Copy diagnostics**
produces one redacted block covering versions, check results, and the last lines
from each service.

### 3. Resilience — failures that are already handled

Some of this exists and should be named rather than rebuilt. Provider cooldown
and failover landed in Phase 9; the service supervisor landed with this phase's
first fix. What is missing:

- **Every long-lived connection reconnects.** The room sidecar, LiveKit, and
  MCP servers each need a documented reconnect policy. Today a dropped sidecar
  is a dead tool until restart.
- **A crashed Gateway does not take the shell with it.** Already true, since the
  shell polls; it needs a test that says so.
- **A failed sub-system degrades rather than cascades.** No vision must not stop
  voice. No provider must not stop the room tools — a light switch does not need
  a model.
- **Nothing retries an unrepeatable action.** Retry is safe for reads and unsafe
  for sends. The external-write idempotency from Phase 5 is the boundary, and
  retry policy has to respect it: **never retry a `spec.external` tool
  automatically.**

### 4. Retry — bounded, and only where it is safe

One helper, used everywhere, rather than a different `for` loop per call site:

- exponential backoff with jitter, because synchronised retries from several
  subsystems are their own outage;
- a cap on attempts *and* on total elapsed time;
- retry only idempotent operations — reads, health checks, reconnects;
- honour `Retry-After` rather than guessing (already true for providers);
- **surface the failure after the last attempt.** A retry that ends in silence
  is worse than the original error, because now there is a delay too.

## Work breakdown

**Step 1 — structured logging.** One logger, one directory, rotation, plus the
redaction test that greps the written file for a planted secret.

**Step 2 — logs reach the UI.** The service supervisor already keeps a tail; the
Doctor page shows it, and Copy diagnostics puts it on the clipboard redacted.

**Step 3 — health checks as a library.** Each check a function returning
pass/warn/fail plus a fix. Used by the page, a CLI, and the tests.

**Step 4 — the Doctor page and `scripts/doctor.ps1`.** The script matters: it
has to work when the shell does not.

**Step 5 — the retry helper**, and converting existing ad-hoc retries onto it.
Includes the guard that refuses to auto-retry an external write.

**Step 6 — reconnect policies** for the sidecar, LiveKit, and MCP.

**Step 7 — degradation tests.** Kill each dependency in turn and assert the rest
still works and says what is wrong.

**Step 8 — a crash breadcrumb.** On an unhandled exception, write what happened
before exiting, so the next launch can say "Marvi stopped unexpectedly last
time" and show it.

## Acceptance evidence

- Every one of the three original failures — `uv` missing, port taken, broken
  imports — produces a **different, correct** message in the UI.
- A log file exists after a clean run, with no key, token, or account content in
  it, proven by grepping the file.
- Doctor runs from a script with the desktop app closed.
- Killing the Gateway mid-session leaves the shell responsive and honest;
  restarting it recovers without restarting the app.
- Killing the room sidecar degrades the room tools only. Voice keeps working.
- An external write is never retried automatically, proven by a test.
- A diagnostics block can be produced in one click and contains nothing secret.

## Open questions

- **How much log is too much?** An always-on assistant writing debug lines all
  day is a disk problem. Default level and rotation size need a real decision,
  not a guess.
- **Does Doctor auto-fix?** Running `uv sync` for the user is genuinely helpful
  and also a command Marvi runs without being asked. Leaning toward
  suggest-and-confirm rather than silent repair.
- **Crash reports stay local.** Marvi is local-first, so nothing uploads. The
  deliverable is a file the user chooses to send.
