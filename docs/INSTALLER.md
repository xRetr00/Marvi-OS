# The installer and updater

`apps/updater` — a Rust core with a Tauri shell. **This is what ships.** Marvi is
not distributed as an electron-builder installer, and the desktop app does not
update itself.

The reason is that an app-bundle installer can only install an app bundle, and
the app is the smallest part of Marvi. What actually has to arrive on a machine
is a git checkout, a Python toolchain, a Node toolchain, and eventually several
gigabytes of models.

## Shape

```
apps/updater/
  crates/core/     headless logic, no GUI dependency, testable against real git
  src-tauri/       thin shell over the core
  ui/              the installer window
```

The core has no Tauri dependency on purpose: it is tested against real `git`
binaries and a fake build runner, which is why the install and update flows have
tests at all.

## What it does

**Install** clones the target ref into a staging directory, provisions the
toolchain, builds, and atomically swaps it into place. A failed install deletes
the staging tree and leaves nothing half-installed.

**Update** fast-forwards or checks out the target, re-checks the toolchain,
rebuilds, and restores the previous commit if the build fails.

**Channels** are the one knob:

| | |
|---|---|
| `Release` | default, opt-out. The latest signed `v*` tag. Never follows a moving branch. |
| `Dev` | opt-in. Fast-forwards `origin/main` and runs whatever is there. |

A smoke test gates both: the Electron entrypoint must exist, or the build is
treated as failed and rolled back.

## `uv` and Node come with it

Neither toolchain is optional — Marvi is a Python service and a Node build — and
neither is left to the user. That was the failure that opened Phase 10: a
GUI-launched Electron does not inherit the PATH a terminal has, so a `uv`
installed afterwards is one the app cannot see, and every symptom of it looked
identical to every other startup failure.

They install **into the state directory** rather than system-wide:

- an uninstall takes them with it instead of leaving tools behind;
- a machine-wide `uv` that someone else manages is not overwritten;
- the path is known, so it can be handed to the build explicitly rather than
  hoped for.

**A tool already on PATH is used as-is.** Downloading a second copy of something
that works wastes bandwidth and disk. Node is the exception: a version below the
required major is treated as absent, because building against it fails later and
less clearly.

The check runs before **every** build — install and update both — because a
release can need a newer toolchain than the one that installed the previous
release, and finding that out partway through `npm ci` is finding out too late
to say anything useful. `NODE_VERSION` in `install.rs` is how a release asks for
a newer one.

The provisioned directories are prepended to `PATH` for the build itself. A
child process that cannot see the toolchain just installed is the exact failure
this exists to prevent.

## One state directory

`%LOCALAPPDATA%\Marvi-OS`. Everything: the checkout marker, update results,
toolchains, logs, databases, identity, models, runtime binaries, skills, MCP
config.

The name is declared once in `crates/core/src/lib.rs` as `STATE_DIR_NAME` and
mirrored in `apps/desktop/src/main/updater.ts` and
`services/gateway/src/marvi_gateway/paths.py`. **All three must agree**, and the
comment in each says so.

It was `Marvi OS` with a space until models and binaries ended up in a second,
hyphenated folder. Two nearly identical names is confusing to look at, and a
space in a path is a nuisance in every shell. Anything left in the old folder is
migrated on first run and the old copies are left in place rather than deleted.

## One at a time

**The desktop takes a single-instance lock.** Two instances would each start a
Gateway on 8765, an agent joining the same LiveKit room, and a vision loop on
the same camera — the second of each failing in a way that looks like a bug
rather than like a second copy, while both write the same databases. A second
launch surfaces the first window instead.

**The bootstrap takes a file lock** in the state directory. Double-clicking the
installer twice, or clicking Update while an install is finishing, would
otherwise run two `git checkout` and `npm ci` passes in one directory. A stale
lock from a crash is reclaimed rather than treated as fatal.

## Shutting down properly

`child.kill()` ends `uv` and leaves the Python it started running. Every Marvi
service is `uv` launching something, so the process that holds the port and the
checkout is a **grandchild**, and on Windows a held file makes `git checkout`
and `npm ci` fail.

So three things happen:

- the desktop kills the whole tree on quit (`taskkill /T` on Windows, process
  group elsewhere), politely first and then not;
- it sweeps for strays at startup, matched by command line rather than by
  executable name, since `python.exe` says nothing and `marvi_gateway` is
  unambiguous;
- the updater clears anything holding the install root before it applies,
  because the desktop exiting is not the same as its children exiting.

## Releases

**There is no per-release installer.** The updater clones the tag and builds it
on the machine, so the tag is the payload; the release attaches the bootstrap
binary and a checksum for first-time installs, and GitHub's own source archives
are the rest.

That makes the CI gates the important part. A tag that cannot be built is a tag
that breaks every Dev-channel update, and the failure lands on a user's machine
rather than in the workflow. So the release job runs the full suite — desktop,
gateway, agent, bootstrap — and then runs **`npm run build:unpack`, the exact
build the updater will run**, and smoke-tests its output.

So the release contract is:

1. Tag `v*` on the repository. The Release channel finds it.
2. The updater clones or fast-forwards to it.
3. The toolchain is re-checked and updated if the release needs a newer one.
4. `npm ci` and `npm run build:unpack`, then the smoke test.
5. On failure, the previous commit is restored.

## The handoff to Marvi

After the checkout and toolchain are in place, everything downstream belongs to
Marvi itself — models, browsers, Python dependencies, skills, MCP servers:

```bash
marvi doctor        # what is missing, and what fixes each thing
marvi setup         # install it
```

`marvi doctor` is the contract test. Zero failures means the installer did its
job; `uv is not on PATH` means it did not, and says so precisely rather than
leaving a broken app with no explanation.

`marvi` must be on PATH and runnable from both `cmd.exe` and PowerShell, because
the CLI is what works when the desktop app does not.

## What the installer deliberately does not decide

**The GPU.** It depends on hardware the installer can see but a preference only
the user holds, and getting it wrong costs a multi-gigabyte reinstall. Setup
asks once and remembers; `MARVI_USE_GPU` set beforehand skips the question,
which is how an unattended install should do it.

**Models.** Gigabytes, and which ones depends on the capabilities the user
actually wants.

**Skills and MCP servers.** Both are trust decisions, and an unattended
installer is the wrong place to make one.

**Provider credentials.** Entered in the app, stored per-user, never shipped.
