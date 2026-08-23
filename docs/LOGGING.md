# Logging

Where to look when something is wrong, and what guarantees the files make.

## Where

`%LOCALAPPDATA%\Marvi OS\logs`, overridable with `MARVI_LOG_DIR`.

| File | What is in it |
|---|---|
| **`errors.log`** | **everything at WARNING and above, from every subsystem** |
| `gateway.log` | HTTP, tool router, confirmations, uvicorn |
| `providers.log` | model calls, tokens, cache hits, cooldowns, failover, `httpx` |
| `voice.log` | the agent worker, LiveKit, STT/TTS, announcements |
| `room.log` | sidecar RPC, device actions, sleep-mode refusals |
| `mind.log` | journal, policy, deliberation, the scheduler |
| `memory.log`, `chat.log` | as named |
| `desktop.log` | the Electron shell: windows, IPC, service supervision |

**Start with `errors.log`.** Each other file answers "what was this subsystem
doing"; `errors.log` answers "what went wrong", which is the question anyone
actually has. It is usually the only file needed.

Smart Room's own camera, face, visitor, device, and automation logs live in
`%LOCALAPPDATA%\Marvi-OS\plugin-data\smart_room\runtime.log`. Gateway records
only its lifecycle/RPC boundary in `room.log`.

Files rotate at 8 MB with three backups (`errors.log` at 4 MB with five, since
it is small and worth more history). Tune with `MARVI_LOG_MAX_BYTES`,
`MARVI_LOG_BACKUPS`, and `MARVI_LOG_LEVEL`.

## The two guarantees

### Nothing is lost

Python discards things in more ways than one file handler catches, so all of
them are claimed:

- **Library loggers.** `httpx`, `uvicorn`, `apscheduler`, and the
  rest are routed to a subsystem rather than ignored. A connection error from
  `httpx` is usually the most useful line in the file.
- **Uncaught exceptions on every thread.** `sys.excepthook` covers the main
  thread only; `threading.excepthook` covers the rest, and a background thread
  dying quietly is exactly the failure nobody notices.
- **Unraisable exceptions** — errors in `__del__` and during collection, which
  normally print to stderr and vanish.
- **asyncio**'s handler, so "task exception was never retrieved" is recorded
  rather than shouted at a stderr nobody reads.
- **Warnings**, including the deprecations that predict the next breakage.
- **Subprocess output.** The supervised services are piped, and their stdout and
  stderr land in their own files.
- **An unmapped logger still lands somewhere** — `gateway.log` — rather than
  being dropped.

### Nothing leaks

Redaction is **value-based, not pattern-based**. Marvi holds its own
credentials, so the filter scrubs those exact strings wherever they appear: in a
message, in a lazy `%s` argument, inside a URL's query string, in a `repr` of a
headers dict, in a traceback. A filter that looked for field names would miss
every one of those.

Pattern matching is a second layer, for tokens Marvi was never handed.

Three details that matter:

- The filter is on the **handlers**, not the loggers, so a library logging
  through its own logger cannot bypass it.
- Tracebacks are **rendered and scrubbed by the filter**, not by the formatter,
  because the formatter runs afterwards — a traceback rendered there would never
  be cleaned, and a secret in a traceback is the likeliest way one reaches disk.
- OAuth access and refresh tokens are registered explicitly with
  `redactor().add()`. They never pass through the environment, so nothing else
  would know to hide them.

Proven by tests that plant a secret and grep the written files. The Doctor's
Copy diagnostics relies on this being true.

## Nothing blocks

Handlers sit behind a `QueueListener`: the calling thread does a queue put, a
background thread does the file I/O. The voice path logs from latency-critical
code, and a disk write there would be audible.

Records are copied onto the queue rather than passed by reference — another
handler on the root logger formatting the same record would otherwise mutate the
object already queued.

## Adding a subsystem

```python
from marvi_gateway.logs import get_logger

log = get_logger("weather")
log.info("it is raining")     # creates weather.log on first write
```

No registry to update and no handler to wire. For a module that should route
somewhere specific, add one entry to `MODULE_SUBSYSTEMS` in `logs.py`.

Existing modules need no change: they use `logging.getLogger(__name__)`, and
routing is by module name.

## The desktop shell

The Electron main process writes its own files, in the same directory and the
same line format. This is deliberate rather than lazy: **the moment those logs
matter most is the moment the Gateway is not running**, so posting them over
HTTP would lose exactly the lines that explain why nothing started. It honours
the same redaction and the same `errors.log` fan-in.

## Doctor

`marvi_gateway/doctor.py` reads these files and everything else. It is a module
inside Marvi rather than a script beside it, so the page, the API and any future
CLI share one implementation. Every finding carries a remedy of one of three
kinds — `automatic` runs unasked, `confirm` waits, `manual` is never executed
and instead names the exact command or settings page.

`GET /doctor`, `POST /doctor/heal`, `GET /doctor/diagnostics`.

## Crashes

An unclean exit writes `last-crash.json` beside the logs. The next launch
reports it once and clears it — a crash nobody is told about is a pattern nobody
spots. The last five are kept.

## Reading them

- `GET /logs?subsystem=errors&lines=300` — already redacted on disk, so there is
  nothing further to strip.
- The Voice and Settings pages show each service's recent output inline.
