# Phase 17 — focused standalone messaging transplant

Status: complete

## Architecture

The shipping path is:

`Marvi OS → bundled marvi_messaging runtime → configured messaging platforms`

Electron resolves the engine from
`services/messaging/marvi_messaging/engine` in a checkout and from
`resources/messaging/runtime/marvi_messaging/engine` in an installed build.
It launches bundled `python.exe -m marvi_messaging.main`; no Git command,
package manager, upstream executable, or external source tree participates.

## Shipped source boundary

Release packaging includes every non-cache file recursively under
`services/messaging/marvi_messaging`. The engine subtree contains these source
families: `acp_adapter`, `acp_registry`, `agent`, `assets`, `cron`, `gateway`,
`locales`, `mcp-research-data`, `native`, `optional-mcps`, `optional-skills`,
`plugins`, `providers`, `runtime_support`, `skills`, `tools`, and `tui_gateway`,
plus the engine's root Python modules, `pyproject.toml`, `uv.lock`, Python pin,
README, and MIT license. Repository UI, website, release workflows, Docker/Nix,
development tests, Git metadata, and upstream installers are not shipped.

## Hard gates

- Live capability manifest: 24 platform values, 23 platform plugins, 123 tools,
  68 toolsets, and 19 slash-command families, exact hashes pinned at source
  commit `61977bb4d6b97ab2aece57d2405fa2f0b19e3ae0`.
- Runtime source contains no predecessor product names, compatibility profile
  variables, or old package/module paths.
- `prepare-messaging-runtime.ps1` copies only the Marvi package, embeds CPython
  3.11.15, installs 140 locked packages at build time, disables index/package
  access, and passes offline imports plus the owned CLI command check.
- The staged runtime returns health and pairing JSON, starts a real gateway,
  reports `running: true` through the PID/status boundary, and stops cleanly.
- Electron tests prove packaged-path preference, Marvi engine environment,
  absence of Git/package-manager operations, and the explicit enable/configure
  startup gate.

## Update boundary

The end user never clones, installs, knows about, or launches the source
project separately. Updating messaging means reviewing a new upstream pin in a
temporary extraction area, rerunning ownership transforms and parity checks,
then committing the resulting Marvi-owned files. Runtime `/update` returns the
Marvi-managed response, and lazy package installation is sealed by
`MARVI_MESSAGING_DISABLE_LAZY_INSTALLS=1`.
