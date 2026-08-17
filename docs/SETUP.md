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

**Known wart:** models and binaries go to `Marvi-OS` (hyphen) while logs,
databases and identity go to `Marvi OS` (space). Two nearly-identical folders is
confusing, and it predates this phase — the PowerShell installers established
the hyphenated one. Unifying means migrating an existing install, so it waits
for step 8, when those scripts are retired and there is one installer to change
rather than two.

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

## Doctor knows about components

`marvi doctor` verifies every component by hash, not by existence. A component
something depends on is a **failure**; one nothing depends on is a warning. The
remedy is `confirm` rather than `automatic`, because gigabytes of download is a
decision — and `marvi doctor --fix` lists those and asks before starting.

## Still to come in Phase 11

- **MCP servers and skills.** Adding an MCP server runs code on this machine, so
  it will name the exact command first; a skill will not be able to grant itself
  tools it was not given. Neither is installed from a URL Marvi found itself.
- **The setup page**, with progress that survives closing it.
- **First-run flow** — the minimum to say the first sentence, not everything.
- **LiveKit and buffalo_l file hashes.** Both are described in the catalog so
  Doctor can report on them, but neither is downloadable yet: LiveKit ships a
  zip and InsightFace fetches its own weights on first use. Listed rather than
  silently missing.
- **Retiring the PowerShell installers**, once this covers them. Deleting a
  working installer before its replacement is proven is how a repo ends up with
  neither.
