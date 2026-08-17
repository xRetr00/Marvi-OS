# Setup

What Marvi installs, and the two ways to drive it.

## One engine, two front ends

The install logic lives in `marvi_gateway/setup/`. The desktop app calls it over
HTTP; the `marvi` CLI calls the same functions in-process. A CLI over a shared
module is not a second product — a PowerShell script would have been a second
*implementation*, and the second implementation is the one that drifts.

**The CLI exists because the desktop app cannot fix the desktop app.** When
Electron will not start or the Gateway will not bind, a button is unreachable.
That is not hypothetical; it is the failure that opened Phase 10. Setup also has
to work before the GUI exists on a fresh machine, and a multi-gigabyte download
belongs somewhere it survives a window closing.

```bash
marvi doctor              # every check, with what fixes each one
marvi doctor --fix        # apply what Marvi can; asks before anything large
marvi setup               # install what is missing
marvi setup voice         # just what the voice path needs
marvi setup --dry-run     # the plan and the size, nothing downloaded
marvi models list         # what is installed, what is missing
marvi models verify voice-stt
marvi models install voice-stt --force
marvi models remove voice-stt
marvi logs errors -n 50
marvi providers
marvi crashes

marvi gpu                 # what was found, and whether to use it
marvi gpu gpu | cpu       # decide and remember
marvi mcp list | add <name> -- <command> [args] | remove | test
marvi skills list | browse | install <name> | remove <name>
marvi paths               # where everything lives
```

None of these touch localhost. They work with the Gateway stopped.

## Components are data

`config/components.json` describes what can be installed: an id, a pinned
revision, and a file map of `{name: [size, sha256]}`. Adding a component means
adding an entry there — nothing in the code knows the name of a specific model.

Voice models are still read from `config/voice-models.json`, because the
PowerShell installers read it too and duplicating five SHA256 hashes across two
files is how they drift apart. When those scripts are retired the entries move
into `components.json` and the seam disappears.

Everything installs under `%LOCALAPPDATA%\Marvi-OS` (`MARVI_INSTALL_ROOT`).

One root, no spaces. Logs, databases, identity, models, runtime binaries,
skills and MCP config all live under it, and every path derives from
`marvi_gateway/paths.py` rather than from a literal in each module.

Anything left in the old space-named folder is moved on first run, without
overwriting: if a file exists in both, the newer root wins and the old copy
stays put, because guessing which of two journals is real is not a silent
decision.

## The four properties

**Verified.** A file is not installed until its hash matches. Size is checked
first because it is free and catches the common case. A truncated model produces
a baffling runtime error hours later in a different subsystem; a hash check
produces a clear one immediately.

**Resumable.** A download writes to `<name>.part` and sends a `Range` header on
the way back, so an interruption costs the bytes since the last write rather
than all of them. Two edge cases are handled explicitly: a part longer than the
expected file is not a prefix, so it starts over; a server that ignores `Range`
and returns 200 is not appended to.

**Idempotent.** Running setup on a complete install verifies and says so, at
zero bytes. That is what makes `marvi setup` safe to run whenever, which is what
makes people actually run it.

**Reversible.** `remove` deletes the component, and refuses if the resolved path
is outside the install root — a manifest should never point outside the tree
Marvi owns, and if one does, deleting it is the wrong response.

### Why the `.part` file matters more than it looks

Writing straight to the final path means a crash mid-download leaves a file that
*looks* installed: right name, right place, wrong contents. Every later check
that trusts existence rather than hashing is then wrong, and the failure shows up
somewhere unrelated.

## Before it starts

Setup reports the total size and refuses if the disk cannot take it with a
margin. Filling a disk halfway through a download breaks considerably more than
the download.

## The GPU question

**Every install and update path asks before installing anything GPU-capable.**
A CPU build of PyTorch on a machine with a good GPU is silent, easy, and costs a
multi-gigabyte reinstall to undo.

Detection layers three sources: `torch.cuda` when torch is already there,
`nvidia-smi` which works before it is, and the Windows device list which sees a
card even with no driver. That last case gets its own answer rather than a
question — a card with no working CUDA is not a choice between GPU and CPU, it
is a missing driver, and Marvi says so.

The answer is remembered in `MARVI_USE_GPU`, so nothing asks twice. Set it
before a first run and the question is skipped, which is how an unattended
install should do it.

## MCP servers

Marvi reads and writes the config shape Claude Desktop, Claude Code, Cursor and
VS Code all use, so a server configured elsewhere pastes straight in:

```json
{"mcpServers": {"files": {"command": "npx", "args": ["-y", "@scope/pkg"]}}}
```

Two conventions are applied for you, because both fail as an unexplained
timeout: `npx` gets `-y` or it stops to ask about installing the package, and
Python servers over stdio get `PYTHONUNBUFFERED=1` or their output sits in a
buffer looking exactly like a hang.

**Adding one is two steps by construction.** An MCP server is not data — it is a
process that runs code with your permissions. `prepare` returns the exact
command and writes nothing; `add` refuses without the single-use token bound to
that exact command. There is no single call that installs a server.

`marvi mcp test <name>` completes a real MCP handshake, because a configured
server that has never been spoken to is one that will fail the first time it
matters.

## Skills

Marvi implements the Agent Skills specification rather than a private format, so
a skill written for another agent works here and one written here works
elsewhere. A skill is a directory with `SKILL.md` — YAML frontmatter with `name`
and `description`, optional `license`, `compatibility`, `metadata` and
`allowed-tools` — plus optional `scripts/`, `references/` and `assets/`.

### `allowed-tools` is a request, never a grant

This is the line that matters. The obvious reading — the skill lists a tool, so
the skill gets it — would mean **any skill grants itself anything by editing a
text file**. A skill arriving with `allowed-tools: send_email` would be
authorised to send email without asking, from a file the user very likely did
not read.

So the declaration is intersected with what Marvi already permits and never
widens it. A sensitive tool stays sensitive. What it actually buys is the
opposite of privilege: it *narrows* a skill to the tools it says it needs.

### The store

`marvi skills browse`, or the Skills page. Sources are GitHub repositories
listed in `config/skill-sources.json`, read through the git trees API — every
skill catalogue worth using is ultimately a repo of directories containing
`SKILL.md`, so there is no vendor API to sign up for and pointing Marvi at a
private collection works the same way.

**Marvi never installs from a source it discovered itself.** Not from a link in
a page, not from a suggestion in a model's output. The list is the list.

Browsing only reads. Installing shows the instructions in full first, because
the body is what will shape behaviour, and resolves `allowed-tools` against
policy before anything is written. `scripts/` is copied but never executed at
install time.

## Doctor knows about components

`marvi doctor` verifies every component by hash, not by existence. A component
something depends on is a **failure**; one nothing depends on is a warning. The
remedy is `confirm` rather than `automatic`, because gigabytes of download is a
decision — and `marvi doctor --fix` lists those and asks before starting.

## Tool dependencies

Browser tools cannot open a page without a browser engine, so Playwright's
Chromium is a component like any other (`marvi setup browser`). A `command` kind
covers installers that own their own download, run through `uv run` inside the
project that pinned the tool rather than whatever is on PATH.

## Still open

- **LiveKit and buffalo_l file hashes.** Both are in the catalog so Doctor can
  report on them, but neither downloads through this path yet: LiveKit ships a
  zip, and InsightFace fetches its own weights on first use. Listed rather than
  silently missing.
- **First-run flow** — the minimum to say the first sentence, rather than
  everything at once.
- **Retiring the PowerShell installers.** Deleting a working installer before
  its replacement is proven is how a repo ends up with neither. When they go,
  the voice model entries move from `voice-models.json` into
  `components.json`.
