# Configuration

The rule: **no base URL, port, model name, key, or behaviour threshold is a
literal in application code.** Everything resolves from the environment, and
everything the user should be able to change is editable from the control
center without a rebuild.

This document is the audit of that rule, and the map of where each thing lives.

## The three places configuration comes from

| Source | What lives there | Who writes it |
|---|---|---|
| `config/runtime.json` | Local service topology: Gateway host/port, LiveKit version and port | committed to the repo |
| `%LOCALAPPDATA%\Marvi OS\providers.env` | Provider keys, models, and proactivity settings | the control center |
| `%LOCALAPPDATA%\Marvi OS\tokens.bin` | OAuth access and refresh tokens, DPAPI-encrypted | the OAuth flow |

Real environment variables **override all three**. Launching with
`OPENAI_API_KEY=...` in the shell is never silently replaced by a stale saved
value.

`runtime.json` exists because the Gateway port used to appear twice in the
desktop main process — once in the spawn arguments, once in the fetch base URL —
and the LiveKit version appeared in three files. Two copies of a port is a bug
waiting for somebody to change one of them.

## Audit results

Swept for hardcoded endpoints, ports, model names, absolute paths, and
behaviour constants across `services/` and `apps/desktop/src`.

### Fixed in this pass

| Was | Now |
|---|---|
| `GATEWAY_BASE_URL = 'http://127.0.0.1:8765'` in the desktop main process, no override | `config/runtime.json` + `MARVI_GATEWAY_URL` |
| Gateway port written separately in the spawn args | derived from the same URL the shell polls |
| LiveKit version `1.13.5` in three files | `config/runtime.json` + `MARVI_LIVEKIT_SERVER` |
| Quiet hours, surface cooldown, daily token budget, speak-when-away as constants | env vars, and editable over `PUT /initiative` |
| OpenCode Go reading `MARVI_LLM_BASE_URL` / `MARVI_LLM_MODEL` | `MARVI_OPENCODE_GO_URL` / `MARVI_OPENCODE_GO_MODEL`, matching every other provider |

### Deliberately still literals, and why

These are **defaults behind an environment lookup**, which is the correct
pattern — a default is not a hardcode, an unoverridable value is:

- `activity.py`, `announce.py`, `room.py`, `web.py` — every URL and port is
  `os.environ.get(NAME, default)`.
- `providers/*.py` — every base URL and model is `base_url_env` /
  `default_model_env` on the profile. That is the registry's whole job.
- `apps/desktop/src/main/config.ts` — one fallback block used only when
  `config/runtime.json` is missing entirely, so a broken install produces a
  running app that can explain itself rather than a crash on line one.

These are **tuning constants**, not user settings. Changing them is a code
change with a test behind it:

- `SPEAK_SAMPLE_RATE`, `JPEG_QUALITY`, `EVENT_TAIL_BYTES` — wire and codec
  details.
- `MAX_TOOL_ROUNDS`, `HISTORY_TURNS`, `MAX_OUTPUT_TOKENS` — bounds that exist to
  cap cost. Exposing them would mostly be a way to make Marvi expensive.
- `REFRESH_MARGIN_SECONDS`, cooldown ceilings — correctness margins.

One genuine remaining gap: `EPISODIC_TTL_DAYS` and `PROMOTE_AFTER_REPEATS` in
`memory.py` shape what Marvi remembers and for how long, which is arguably a
user preference. Left as constants for now and recorded here rather than
quietly ignored.

## Environment variables

### Services and topology

| Variable | Default | Meaning |
|---|---|---|
| `MARVI_GATEWAY_URL` | from `runtime.json` | where the Gateway listens and is polled |
| `MARVI_LIVEKIT_SERVER` | from `runtime.json` version | path to `livekit-server.exe` |
| `LIVEKIT_URL` | `ws://127.0.0.1:7880` | room server |
| `MARVI_UV_PATH` | searched | `uv` binary, when it is not on PATH |
| `MARVI_MANAGE_VOICE_STACK` | on | set `0` to run the services yourself |

### Storage

| Variable | Default |
|---|---|
| `MARVI_PROVIDER_CONFIG` | `%LOCALAPPDATA%\Marvi OS\providers.env` |
| `MARVI_TOKEN_STORE` | `%LOCALAPPDATA%\Marvi OS\tokens.bin` |
| `MARVI_JOURNAL_DB` | `%LOCALAPPDATA%\Marvi OS\journal.sqlite3` |
| `MARVI_CHAT_DB` | `%LOCALAPPDATA%\Marvi OS\chat.sqlite3` |
| `MARVI_INSTALL_ROOT` | `%LOCALAPPDATA%\Marvi-OS` |
| `MARVI_IDENTITY_DIR` | `%LOCALAPPDATA%\Marvi OS` |

### Logging and identity

| Variable | Default | Meaning |
|---|---|---|
| `MARVI_LOG_DIR` | `%LOCALAPPDATA%\Marvi OS\logs` | where the per-subsystem files go |
| `MARVI_LOG_LEVEL` | `INFO` | |
| `MARVI_LOG_MAX_BYTES` | 8 MB | rotation size per file |
| `MARVI_LOG_BACKUPS` | 3 | |
| `MARVI_INSTALL_ROOT` | `%LOCALAPPDATA%\Marvi-OS` |
| `MARVI_IDENTITY_DIR` | `%LOCALAPPDATA%\Marvi OS` | where `SOUL.md` and `USER.md` live |
| `MARVI_IDENTITY_BUDGET` | 1200 | tokens of identity paid on every turn |

See `docs/LOGGING.md` and `docs/IDENTITY.md`.

### Proactivity — all editable from the Mind page

| Variable | Default | Meaning |
|---|---|---|
| `MARVI_INITIATIVE` | on | master switch |
| `MARVI_QUIET_START` / `MARVI_QUIET_END` | 23 / 8 | hours Marvi stays quiet |
| `MARVI_SURFACE_COOLDOWN` | 900 | seconds between surfacing the same thing |
| `MARVI_DAILY_TOKEN_BUDGET` | 200000 | tokens of background thinking per day |
| `MARVI_SPEAK_WHEN_AWAY` | off | speak to an empty room |

Bad values are **clamped rather than obeyed**: a typo in a config file must not
be able to switch proactivity off by accident, or leave the budget uncapped.

Providers have their own table in `docs/PROVIDERS.md`.
