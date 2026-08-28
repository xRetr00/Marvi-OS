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

**Marvi installs its own copies even when the tools are already on PATH.** The
original design reused whatever was there, which looked like it saved a
download. It did not: the PATH a developer's terminal has is not the PATH a
GUI-launched app inherits, so "found during install" and "usable at runtime" are
different questions and only the second one matters. v0.1.3 shipped with neither
tool installed, because both were found and skipped.

What is on PATH is still reported — it is useful to see — and the installer says
out loud that it is downloading a copy anyway, because silence there reads as a
bug.

That change also uncovered the reason it had never been noticed: the `uv`
installer command had been broken since it was written. It ran a PowerShell
one-liner through `cmd /d /s /c`, and Rust's argument escaping targets the C
runtime parser rather than `cmd`'s, so the quoting arrived mangled and the
command failed in about a second. On any machine that already had `uv`, that
code never ran. PowerShell is now invoked directly, and there is a live test
(`cargo test -p marvi-bootstrap-core --test toolchain_live -- --ignored`) that
does a real download, because that is the only kind of test that would have
caught it.

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
Gateway on 8765, an agent joining the same LiveKit room, and the owned Smart
Room sidecar — the second of each failing in a way that looks like a bug
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
- the desktop starts the bootstrap with the checkout root as its working
  directory, and the bootstrap moves itself to the state directory before
  creating its window. This prevents Windows from pinning
  `apps/desktop/dist` through an inherited current-directory handle.

The bootstrap window closes itself only after an `ok` result has been written.
Failed, skipped, and aborted runs stay open with recovery guidance, a selectable
technical log, and an explicit Close updater action.

The window receives three distinct event classes: one metadata/stage manifest,
named milestone transitions, and raw log lines. Only milestone transitions can
change the active stage or percentage. The renderer sends `ui-ready` after all
listeners are registered, so startup metadata such as the channel cannot be
lost during WebView initialization. Logs are bounded and hidden behind Show
details during normal operation; a failed run opens them automatically.

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

A checkout that builds is not an installation. v0.1.3 finished with no LiveKit
server, no `marvi` command and no shortcut, every one of which reads as "Marvi
is broken" rather than "the installer stopped early". So `handoff.rs` runs four
more steps, on install **and** on update — an existing installation predates all
of this, and updating is how those machines get it:

| | |
|---|---|
| **The GPU answer** | Asked in the installer window, before anything reads it. It picks the PyTorch index, and getting it wrong costs a multi-gigabyte reinstall. `--gpu` / `--cpu` answers it unattended; unanswered leaves it to Marvi's own detection. |
| **Essential components** | `marvi setup --essential`: the LiveKit server and the two Python environments. Which ones is the catalog's decision (`"essential": true`), not the installer's. |
| **`marvi` on PATH** | A `.cmd` shim in `bin/`, **prepended** to the user's PATH — another tool's `marvi` was winning. A shim, not a copy, so an update never leaves a stale CLI behind. |
| **Shortcuts** | Desktop and Start menu, pointing at the built executable found under `apps/desktop/dist`. |

Every step is best-effort and reports what it did: a missing shortcut is not a
reason to undo a working install, but it is a reason to say so.

Everything larger stays with the user — models, browsers, skills, MCP servers:

```bash
marvi doctor        # what is missing, and what fixes each thing
marvi setup         # install it
```

`marvi doctor` is the contract test. Zero failures means the installer did its
job; `uv is not on PATH` means it did not, and says so precisely rather than
leaving a broken app with no explanation.

## The window

Resizable, minimisable, with a title bar, and **not** always on top. It was none
of those, which meant a fifteen-minute install sat over everything the user was
doing with no way to move it aside.

It also shows a scrolling log. `npm ci` and `uv sync` are the slow parts and the
parts that fail, and their output used to go to `/dev/null` — so the window
showed one word for fifteen minutes, which is indistinguishable from a hang, and
then either finished or said `npm exited with 1`, which explains nothing. Output
is now streamed line by line, and the last 25 lines are carried into the error
message.

## What the installer deliberately does not decide

**Models.** Gigabytes, and which ones depends on the capabilities the user
actually wants.

**Skills and MCP servers.** Both are trust decisions, and an unattended
installer is the wrong place to make one.

**Provider credentials.** Entered in the app, stored per-user, never shipped.
