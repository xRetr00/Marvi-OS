# Installing and updating Marvi

## The bootstrap installer owns this, not Electron

Marvi is **not** distributed as an electron-builder installer. The bootstrap
installer and updater are the shipping vehicle, and everything below is the
contract this repository holds up its end of.

The reason is that an Electron installer can only install the Electron app, and
the Electron app is the smallest part of Marvi. What actually has to arrive on a
machine is a git checkout, a Python toolchain, a Node toolchain, and several
gigabytes of models — none of which an app bundle is good at.

## What the installer provides

**`uv` and Node ship with the installer.** They are not assumed to be present
and not left to the user to install. This is the same choice other agent
products make, and it is the direct fix for the failure that opened Phase 10: a
GUI-launched Electron does not inherit the PATH a terminal has, so a `uv`
installed later is a `uv` the app cannot see.

The installer is responsible for:

| | |
|---|---|
| The checkout | clone or update from the GitHub repository |
| `uv` | install, put on PATH, and **check and update on every run** |
| Node | same |
| Paths | create `%LOCALAPPDATA%\Marvi-OS`, and put `marvi` on PATH |
| Updates | fetch the release package, apply it, re-check the toolchain |

Marvi is responsible for everything downstream of that: models, binaries,
Python dependencies, browsers, skills, MCP servers. All of it through
`marvi setup` and the Setup page, which is one implementation the installer can
also call.

## The handoff

After the installer has placed the checkout and the toolchain:

```bash
marvi doctor        # what is missing, and what fixes each thing
marvi setup         # install it
```

`marvi doctor` is the contract test. If it reports zero failures, the installer
did its job. If it reports `uv is not on PATH`, the installer did not — and it
says so precisely rather than leaving a broken app with no explanation.

**`marvi` must be on PATH** and runnable from both `cmd.exe` and PowerShell.
That is an installer responsibility, and it matters because the CLI is what
works when the desktop app does not.

## Releases

Each release ships a package the updater applies, rather than an installer the
user re-runs. The updater then re-checks `uv` and Node and updates them if the
new release needs newer ones.

Version and toolchain expectations live in `config/runtime.json`, so the
installer and Marvi read the same numbers instead of each holding their own.

## The GPU question belongs to setup, not the installer

The installer should **not** decide this. Whether to install CUDA or CPU builds
depends on hardware the installer can see but on a preference only the user
holds, and getting it wrong costs a multi-gigabyte reinstall.

So the installer installs the toolchain, and the first `marvi setup` (or the
Setup page) asks once and remembers. See `MARVI_USE_GPU` in
`docs/CONFIGURATION.md`; setting it before the first run skips the question,
which is how an unattended install should do it.

## One root

Everything Marvi writes lives under `%LOCALAPPDATA%\Marvi-OS` — logs, databases,
identity, models, runtime binaries, skills, MCP config. One folder to back up
and one to delete.

There used to be a second folder with a space in the name. Marvi migrates
anything left in it on first run and leaves the old copies in place rather than
deleting them, so nothing is lost if the move was not what you wanted.

## What is not the installer's job

- **Provider credentials.** Those are entered in the app, stored per-user, and
  never shipped.
- **Models.** Several gigabytes that depend on which capabilities the user
  actually wants. Setup asks; the installer does not guess.
- **Skills and MCP servers.** Both are trust decisions, and an installer running
  unattended is the wrong place to make one.
