# Phase 11 — Setup: dependencies, models, skills, and MCP

**Status:** complete
**Depends on:** Phase 10 (the check-and-remedy engine this is built on)

## The decision: one engine, two front ends

The question was whether setup should be a CLI (`marvi setup`, `marvi mcp add`,
`marvi skill install`) or handled from the desktop app. **Both, over one
implementation** — and the reason is that the choice as posed is a false one.

The install logic has to live somewhere regardless. Put it in
`marvi_gateway/setup/` and the two surfaces become thin:

- the **desktop app** calls it over HTTP, the same way the Providers page calls
  the registry;
- the **CLI** calls the same Python functions directly, in-process.

A CLI on top of an existing module is roughly a hundred and fifty lines of
`argparse`. `uv` gives the entry point for free — one line in
`services/gateway/pyproject.toml` and `marvi` is on the PATH. That is not
building a second product, and it is emphatically not the PowerShell-script
pattern being retired in Phase 10, because a script is a *second
implementation* and this is the *same* one.

### Why a CLI is worth having at all

Four reasons, and the first is the one that settles it:

1. **The desktop app cannot fix the desktop app.** When Electron will not start,
   or the Gateway will not bind, a GUI button is unreachable. This is not
   hypothetical — it is precisely the failure that started Phase 10.
2. **Setup precedes the GUI.** A fresh machine, a clean clone, CI. Something has
   to work before anything is installed.
3. **Long downloads belong in a terminal.** Several gigabytes of model weights
   with real progress, resumable, surviving the app being closed.
4. **Scriptable.** Provisioning a second machine should be one command, not
   twenty clicks.

### The command surface

```
marvi setup                    everything missing, in dependency order
marvi setup voice              just the voice stack
marvi doctor                   Phase 10's checks, in a terminal
marvi doctor --fix             apply every automatic and one-click remedy
marvi models list | install | verify | remove
marvi mcp list | add <name> | remove <name> | test <name>
marvi skill list | install <source> | remove <name>
marvi logs [subsystem] [--follow]
marvi provider list | connect <name>
```

`marvi doctor` in a terminal is the same Doctor as the page — same module, same
checks, same remedies. It works when the Gateway is down because it imports the
library rather than calling the server.

## What setup actually installs

Each component is a **manifest entry**, not code. `config/voice-models.json`
already has the right shape — id, revision, files, sizes, SHA256 — and this
phase generalises that pattern rather than inventing one.

| Component | Source | Verified by |
|---|---|---|
| Python environment | `uv sync` per service | lockfile |
| Voice models — STT, TTS | Hugging Face | size + SHA256, already in `config/voice-models.json` |
| Vision model — `buffalo_l` | InsightFace | size + SHA256 |
| PocketTTS | Hugging Face | size + SHA256 |
| LiveKit server | GitHub release | version in `config/runtime.json` + SHA256 |
| MCP servers | user-supplied command or package | a successful handshake |
| Skills | a directory of instructions | schema validation |

Three properties every install must have:

- **Verified.** A download is not finished until its hash matches. A truncated
  model produces a baffling runtime error hours later; a hash check produces a
  clear one immediately.
- **Resumable and idempotent.** Re-running setup on a complete install does
  nothing and says so. An interrupted download continues.
- **Reversible.** Everything lands under `%LOCALAPPDATA%\Marvi OS`, and
  `remove` takes it away. Nothing is written outside that tree and the repo.

## Skills and MCP need a trust decision

Models are data. **Skills and MCP servers are not** — a skill is instructions
that shape behaviour, and an MCP server is a process that executes code and
exposes tools. Installing one is a materially bigger decision than downloading
weights, and the setup system must treat it that way:

- **An MCP server runs code on this machine.** Adding one requires an explicit
  confirmation naming the command that will run. Its tools then enter through
  the existing router, so they inherit confirmation and audit (ADR-016) rather
  than getting a private path.
- **A skill's content is instructions, and it is not the user's writing.** It
  goes in as trusted-but-scoped: it may shape how Marvi does a task, and it may
  not grant itself tools it was not given. A skill that arrives with "you may
  send email without asking" does not get to mean that.
- **Neither is installed from a URL Marvi found itself.** The source is always
  something the user named.

This is the same boundary the rest of the system already draws, applied to a new
kind of input.

## Work breakdown

**Step 1 — the component manifest. Done.** `config/components.json`, the same
shape `voice-models.json` already had: an id, a pinned revision, and a file map
of `{name: [size, sha256]}`. Voice models are still read from the older file
because the PowerShell installers read it too, and duplicating five hashes is
how two files drift apart.

**Step 2 — install, verify, remove. Done.** Verified by hash before anything is
moved into place, resumable through a `.part` file and a `Range` header,
idempotent on a complete install, and reversible with a guard against a manifest
that points outside the install root. Disk space is checked before the first
byte. Proven end to end against a real Hugging Face download. 24 tests.

**Step 3 — the CLI. Done.** `marvi` as a console script: `doctor`,
`doctor --fix`, `setup`, `models`, `logs`, `providers`, `crashes`,
`diagnostics`. Nothing calls localhost, so it works with the Gateway stopped —
which is the entire reason it exists. `--fix` lists consequential remedies and
asks before starting a multi-gigabyte download.

**Step 3b — Doctor sees components. Done.** The check Phase 10 deferred here,
because verifying a hash needs a manifest to check against and writing that
twice would have been worse than waiting.

**Step 4 — the setup page. Done.** What is installed, what is missing, sizes
before downloading, install and remove per component, and the GPU question
first — because it changes which packages get installed, and answering it
afterwards means a multi-gigabyte reinstall.

**Step 5 — first-run flow. Done.** `marvi status`, and `GET /setup/first-run`.
The minimum is computed rather than scripted, and it is smaller than it looks:
**one provider and nothing else.** Marvi thinks, chats, remembers and uses every
local tool with no models at all. Voice is gigabytes and vision needs a camera;
both are additions to a working assistant, not prerequisites for one. Steps
report whether they are already done, so a half-set-up machine resumes rather
than restarts.

**Step 6 — MCP. Done.** The config shape every other agent uses, the two
conventions that otherwise fail as unexplained timeouts, and a two-step add
where `prepare` shows the exact argv and `add` refuses without a single-use
token bound to it. `test` completes a real handshake.

**Step 7 — skills. Done.** The Agent Skills specification rather than a private
format. `allowed-tools` intersected with policy and never widened. A store over
GitHub repository trees, verified against `anthropics/skills`. Structural rules
are hard errors; style limits are warnings, because a store that hides real
skills to enforce a style rule is worse than one that shows them with a note.

**Step 7b — GPU. Done.** Every install and update path asks before installing
anything GPU-capable, layered detection, and a remembered answer.

**Step 7c — one path root. Done.** `Marvi-OS`, no spaces, everything derived
from `paths.py`, with a non-destructive migration out of the old folder.

**Step 7d — the installer owns the toolchain. Done.** `apps/updater` is the
shipping vehicle — a Rust core with a Tauri shell, not electron-builder — and it
now provisions `uv` and Node into the state directory before every build,
install and update alike. See `docs/INSTALLER.md`.

**Step 8 — retire the PowerShell setup scripts. Done.**

The blocker was real and specific: `setup-voice-models.ps1` did not only
download from Hugging Face, it cloned VibeVoice for the TTS speaker voices —
`.pt` files that exist in that repository and nowhere else. Retiring the script
without that would have left a `marvi setup voice` that installs the TTS model
and gives it no voice to speak in.

So a `git` source type was added: sparse checkout plus a shallow fetch of one
pinned commit. The obvious version — a blobless clone then
`git checkout <rev> -- <path>` — looks right and fails, because with
`--filter=blob:none` the blobs were never fetched and a path-limited checkout
cannot lazily fetch them. Sparse checkout declares what is wanted *before* the
fetch, so only those blobs come down.

Verified against the real repository: 25 voice files including the configured
default, idempotent on re-run, and removable.

Both scripts are deleted. `marvi setup voice` and `marvi models verify` cover
everything they did.

## Acceptance evidence

| Evidence | State |
|---|---|
| A corrupted model is detected by hash, not by existence | **done** |
| An interrupted download resumes rather than restarting | **done** |
| Re-running setup on a complete install changes nothing and says so | **done** |
| `marvi doctor` works with the Gateway stopped and the app closed | **done** |
| Adding an MCP server confirms the exact command first | **done** — two-step, single-use token bound to the argv |
| A skill claiming new permissions does not receive them | **done** — intersected with policy, never widened |
| Every install path asks about the GPU before installing PyTorch | **done** |
| One state directory, agreed by Rust, TypeScript and Python | **done** — asserted by a test on each side |
| The installer provisions `uv` and Node, and re-checks on update | **done** |
| A clean machine reaches a working voice session with one command | **done** — `marvi setup voice`, including the TTS voices |
- `remove` leaves nothing behind outside the repo.

## Open questions

- **Where do skills come from?** A local directory is obvious. A registry is a
  supply-chain question, and the answer is probably "not yet".
- **How much does first-run install by default?** The voice stack is gigabytes.
  A first run that downloads everything before saying hello is a bad first run;
  the minimum should be genuinely minimal, with the rest offered.
- **Does the CLI ship in the packaged build**, or only in the git install?
  Marvi already ships as a checkout for the updater's sake, so the CLI comes
  along either way — but it needs to be on the PATH to be useful, and that is an
  installer decision.
