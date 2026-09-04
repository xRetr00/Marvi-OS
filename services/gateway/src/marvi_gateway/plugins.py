"""Desktop plugins: git-installed backends that run as Gateway sidecars.

Marvi has three extension points and they are not interchangeable:

| | what it is | how it runs |
|---|---|---|
| **Skill** | a `SKILL.md` prompt plus files | text, loaded into a turn |
| **MCP server** | someone else's tool process | stdio, spoken to over MCP |
| **Plugin** *(here)* | a backend Marvi owns | a supervised child process |

A plugin is the heaviest of the three: it ships a long-running runtime, owns
hardware or state of its own, and registers tools that talk to it. The Smart
Room engine is the first one, and it is the reason this exists — its state and
RPC token previously lived outside Marvi's application data, so the desktop
could only talk to a room that another application had started. Marvi now
installs the plugin itself, gives it a Marvi-owned data root, and runs it.

## The contract

`plugin.yaml` at the repository root, which is the plugin's own file and is read
rather than imposed:

```yaml
name: smart_room          # the import name, and the data directory name
version: 0.6.0
kind: backend
platforms: [windows]      # skipped elsewhere, and said out loud
pip_dependencies: [...]   # installed into the Gateway environment
provides_tools: [...]     # declared, and checked against what registers
hooks: [on_gateway_start, on_gateway_stop]
```

The Python side is a package exposing `register(ctx)`. `ctx` needs exactly three
methods — `register_tool`, `register_context_provider`, `register_hook` — which
is a small enough host surface to implement honestly rather than approximate.

## Import and data contract

**Plugins import as `plugins.<name>`.** That is the layout the first plugin was
written for, and it is a reasonable one: it namespaces plugins away from
whatever else is on `sys.path`. A `plugins` namespace package is created in the
install root and that root is put on the path.

**Plugin data belongs to Marvi.** Before importing a plugin, the host exports
`MARVI_PLUGIN_DATA`. Plugins derive their own subdirectory from that root and
must not import private host modules to discover paths.

## What a plugin is not allowed to do

**Widen its own permissions.** A plugin's tools are registered through the same
router, audit log and confirmation flow as everything else. `register_tool` is a
*request*, and a plugin asking for a tool to run unconfirmed does not get it:
the policy already in `room.py` — sleep mode permits only switching a light off,
and YOLO cannot override that — is not something a plugin can opt out of.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths
from .logs import get_logger

log = get_logger("plugins")

#: How long a clone, a pull or a dependency install may take.
GIT_TIMEOUT = 300
PIP_TIMEOUT = 900

#: The lifecycle events Marvi raises. A plugin may register for any of them; one
#: it does not know about is simply never called.
HOOKS = ("on_gateway_start", "on_gateway_stop")


class PluginError(Exception):
    """Anything that stops a plugin being installed, loaded or started."""


@dataclass(frozen=True)
class PluginSource:
    """One entry from `config/plugin-sources.json`."""

    name: str
    repo: str
    title: str = ""
    why: str = ""
    #: A branch follows the repository; a tag freezes it. Empty means "whatever
    #: the remote's default branch is" — `main` was assumed once and the first
    #: plugin turned out to be on `master`, which cost an install to find out.
    ref: str = ""
    trusted: bool = False


@dataclass(frozen=True)
class Manifest:
    """`plugin.yaml`, as the plugin wrote it."""

    name: str
    version: str = ""
    description: str = ""
    kind: str = "backend"
    platforms: tuple[str, ...] = ()
    pip_dependencies: tuple[str, ...] = ()
    provides_tools: tuple[str, ...] = ()
    hooks: tuple[str, ...] = ()

    def runs_here(self) -> tuple[bool, str]:
        """Whether this machine is one the plugin claims to support."""
        if not self.platforms:
            return True, "no platform restriction"
        here = platform.system().lower()
        if here in {p.lower() for p in self.platforms}:
            return True, here
        return False, f"{self.name} supports {', '.join(self.platforms)}, not {here}"


def root() -> Path:
    """Where plugins are checked out. On the path, so `plugins.<name>` imports."""
    configured = os.environ.get("MARVI_PLUGIN_ROOT", "").strip()
    return Path(configured) if configured else paths.root() / "plugins"


def data_root() -> Path:
    """Where plugins keep their own state. Separate from the checkout, so an
    update or a reinstall cannot take a user's room history with it."""
    configured = os.environ.get("MARVI_PLUGIN_DATA", "").strip()
    return Path(configured) if configured else paths.root() / "plugin-data"


def install_dir(name: str) -> Path:
    return root() / name


# -- the source list -----------------------------------------------------------


def sources(repo_root: Path) -> list[PluginSource]:
    """Every plugin Marvi knows how to install. Data, not code."""
    path = repo_root / "config" / "plugin-sources.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("could not read plugin-sources.json: %s", exc)
        return []
    found = []
    for entry in raw.get("plugins", []):
        try:
            found.append(
                PluginSource(
                    name=str(entry["name"]),
                    repo=str(entry["repo"]),
                    title=str(entry.get("title", entry["name"])),
                    why=str(entry.get("why", "")),
                    ref=str(entry.get("ref", "")).strip(),
                    trusted=bool(entry.get("trusted", False)),
                )
            )
        except (KeyError, TypeError) as exc:
            # One malformed entry must not hide the rest of the list.
            log.warning("skipping a malformed plugin entry: %s", exc)
    return found


def source_for(repo_root: Path, name: str) -> PluginSource | None:
    return next((s for s in sources(repo_root) if s.name == name), None)


# -- the manifest --------------------------------------------------------------


def read_manifest(directory: Path) -> Manifest:
    """Parse `plugin.yaml`.

    Deliberately a small hand parser rather than a PyYAML dependency: the file
    is flat scalars and string lists, and the Gateway should not grow a
    dependency for four shapes. Anything more complex is a sign the manifest is
    doing too much.
    """
    path = directory / "plugin.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PluginError(f"no plugin.yaml in {directory}: {exc}") from exc

    scalars: dict[str, str] = {}
    lists: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t", "-")) and current:
            item = line.strip().lstrip("-").strip().strip("\"'")
            if item:
                lists.setdefault(current, []).append(item)
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip().strip("\"'")
        if value:
            scalars[key] = value
            current = None
        else:
            current = key
            lists.setdefault(key, [])

    name = scalars.get("name", "").strip()
    if not name:
        raise PluginError(f"{path} declares no name")
    return Manifest(
        name=name,
        version=scalars.get("version", ""),
        description=scalars.get("description", ""),
        kind=scalars.get("kind", "backend"),
        platforms=tuple(lists.get("platforms", ())),
        pip_dependencies=tuple(lists.get("pip_dependencies", ())),
        provides_tools=tuple(lists.get("provides_tools", ())),
        hooks=tuple(lists.get("hooks", ())),
    )


# -- install and update --------------------------------------------------------


def _git(args: list[str], cwd: Path, timeout: int = GIT_TIMEOUT) -> str:
    finished = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if finished.returncode != 0:
        raise PluginError(
            f"git {' '.join(args)} failed: {(finished.stderr or finished.stdout).strip()[:300]}"
        )
    return finished.stdout.strip()


def installed(name: str) -> bool:
    return (install_dir(name) / "plugin.yaml").is_file()


def install(source: PluginSource, repo_root: Path) -> str:
    """Clone a plugin and install its dependencies. Idempotent."""
    target = install_dir(source.name)
    if installed(source.name):
        return update(source.name, repo_root)

    target.parent.mkdir(parents=True, exist_ok=True)
    # Shallow: a plugin's history is not something Marvi needs a copy of.
    # Without --branch, git takes the remote's own default, which is the right
    # answer more often than any name this code could guess.
    argv = ["clone", "--depth", "1"]
    if source.ref:
        argv += ["--branch", source.ref]
    _git([*argv, source.repo, source.name], cwd=target.parent)
    log.info("cloned plugin %s from %s", source.name, source.repo)
    _ensure_namespace_package()
    sync_dependencies(source.name, repo_root)
    return f"installed {source.name}"


def update(name: str, repo_root: Path) -> str:
    """Fast-forward a plugin to its ref and re-check dependencies.

    The user's own plugin repository is the one they push to, so an update is
    the normal way a change reaches Marvi.
    """
    target = install_dir(name)
    if not installed(name):
        raise PluginError(f"{name} is not installed")
    before = _git(["rev-parse", "HEAD"], cwd=target)
    _git(["fetch", "--depth", "1", "origin"], cwd=target)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=target)
    _git(["reset", "--hard", f"origin/{branch}"], cwd=target)
    after = _git(["rev-parse", "HEAD"], cwd=target)
    if before == after:
        return f"{name} is already up to date"
    log.info("updated plugin %s", name, extra={"marvi_from": before[:8], "marvi_to": after[:8]})
    sync_dependencies(name, repo_root)
    # Python imported the old code when the Gateway started and will go on
    # running it. Updating a plugin and watching nothing change is worse than
    # an update that fails, so the new code is not silently pretended to be
    # live -- and `on_gateway_start`, which is what starts a plugin's sidecar,
    # has already been and gone.
    note_not_running(name, f"updated to {after[:8]}; restart Marvi to load it")
    return f"updated {name} ({before[:8]} to {after[:8]}) - restart Marvi to load it"


def sync_dependencies(name: str, repo_root: Path) -> str:
    """Install a plugin's `pip_dependencies` into the Gateway environment.

    Into the Gateway's own environment on purpose: the plugin's tools run
    in-process, so a separate environment would not be importable. That does
    mean a plugin can affect the Gateway's dependency set, which is exactly why
    installing one is a trust decision and not a background convenience.
    """
    manifest = read_manifest(install_dir(name))
    if not manifest.pip_dependencies:
        return "no dependencies"
    from .doctor import find_uv

    uv = find_uv()
    if not uv:
        raise PluginError("uv was not found; cannot install plugin dependencies")
    finished = subprocess.run(
        [uv, "pip", "install", "--python", sys.executable, *manifest.pip_dependencies],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=PIP_TIMEOUT,
        check=False,
    )
    if finished.returncode != 0:
        raise PluginError(
            f"installing {name} dependencies failed: "
            f"{(finished.stderr or finished.stdout).strip()[:300]}"
        )
    log.info(
        "installed dependencies for %s",
        name,
        extra={"marvi_packages": ", ".join(manifest.pip_dependencies)},
    )
    return f"installed {len(manifest.pip_dependencies)} package(s)"


def remove(name: str) -> str:
    """Delete a plugin's checkout. Its data is left alone."""
    import shutil

    target = install_dir(name)
    if not target.exists():
        return f"{name} is not installed"
    resolved = target.resolve()
    if resolved.parent != root().resolve():
        # A name that escapes the plugin root is not a plugin name.
        raise PluginError(f"refusing to remove {resolved}, which is outside {root()}")
    shutil.rmtree(resolved, ignore_errors=True)
    log.info("removed plugin %s (data kept in %s)", name, data_root() / name)
    return f"removed {name}; its data is still in {data_root() / name}"


# -- making a plugin importable ------------------------------------------------


def _ensure_namespace_package() -> None:
    """Create `plugins/__init__.py` and put the root on `sys.path`.

    Plugins import as `plugins.<name>`, so `plugins` has to be a package and its
    parent has to be importable.
    """
    base = root()
    base.mkdir(parents=True, exist_ok=True)
    marker = base / "__init__.py"
    if not marker.exists():
        marker.write_text(
            '"""Marvi desktop plugins. Written by marvi_gateway.plugins."""\n',
            encoding="utf-8",
        )
    parent = str(base.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)


# -- the host side of the contract ---------------------------------------------


@dataclass
class ToolRequest:
    """A tool a plugin asked to register. A request, never a grant."""

    name: str
    schema: dict[str, Any]
    handler: Callable[..., Any]
    toolset: str = ""
    check: Callable[[], Any] | None = None
    emoji: str = ""


@dataclass
class PluginContext:
    """What a plugin's `register(ctx)` is handed.

    Collects requests rather than performing them, so the caller decides what
    to do with each one. A plugin cannot reach into the tool router, the audit
    log or the confirmation flow; it can only ask.
    """

    plugin: str
    tools: list[ToolRequest] = field(default_factory=list)
    context_providers: dict[str, Callable[..., Any]] = field(default_factory=dict)
    hooks: dict[str, list[Callable[..., Any]]] = field(default_factory=dict)

    def register_tool(
        self,
        name: str,
        schema: dict[str, Any],
        handler: Callable[..., Any],
        toolset: str = "",
        check_fn: Callable[[], Any] | None = None,
        emoji: str = "",
        **_ignored: Any,
    ) -> None:
        self.tools.append(
            ToolRequest(
                name=name,
                schema=schema,
                handler=handler,
                toolset=toolset or self.plugin,
                check=check_fn,
                emoji=emoji,
            )
        )

    def register_context_provider(self, name: str, handler: Callable[..., Any]) -> None:
        self.context_providers[name] = handler

    def register_hook(self, event: str, handler: Callable[..., Any]) -> None:
        if event not in HOOKS:
            # Not an error: a plugin may know about a host event Marvi does not
            # raise. Recorded so the reason it never fires is discoverable.
            log.info("plugin %s registered unknown hook %s", self.plugin, event)
        self.hooks.setdefault(event, []).append(handler)


@dataclass
class LoadedPlugin:
    name: str
    manifest: Manifest
    context: PluginContext
    module: Any


def load(name: str) -> LoadedPlugin:
    """Import a plugin and collect what it registers. Starts nothing."""
    directory = install_dir(name)
    if not installed(name):
        raise PluginError(f"{name} is not installed")
    manifest = read_manifest(directory)

    supported, why = manifest.runs_here()
    if not supported:
        raise PluginError(why)

    _ensure_namespace_package()
    os.environ["MARVI_PLUGIN_DATA"] = str(data_root())

    try:
        module = importlib.import_module(f"plugins.{name}")
    except Exception as exc:
        raise PluginError(f"importing {name} failed: {exc}") from exc

    register = getattr(module, "register", None)
    if not callable(register):
        raise PluginError(f"{name} has no register(ctx)")

    context = PluginContext(plugin=name)
    try:
        register(context)
    except Exception as exc:
        raise PluginError(f"{name}.register() failed: {exc}") from exc

    # Declared and delivered should agree; when they do not, the manifest is
    # what a person read, so the difference is worth surfacing.
    declared = set(manifest.provides_tools)
    actual = {t.name for t in context.tools}
    if declared and declared != actual:
        log.warning(
            "plugin %s tool mismatch",
            name,
            extra={
                "marvi_missing": ", ".join(sorted(declared - actual)) or "none",
                "marvi_extra": ", ".join(sorted(actual - declared)) or "none",
            },
        )
    log.info(
        "loaded plugin %s",
        name,
        extra={"marvi_version": manifest.version, "marvi_tools": str(len(context.tools))},
    )
    return LoadedPlugin(name=name, manifest=manifest, context=context, module=module)


def fire(loaded: LoadedPlugin, event: str) -> list[str]:
    """Raise a lifecycle event. Failures are reported, never raised.

    `on_gateway_stop` runs during shutdown, where an exception would leave the
    rest of the shutdown undone; and a plugin that cannot start is a degraded
    Marvi, not a broken one.
    """
    problems = []
    for handler in loaded.context.hooks.get(event, []):
        try:
            handler()
        except Exception as exc:
            problems.append(f"{loaded.name}.{event}: {exc}")
            log.error("plugin hook failed", extra={"marvi_error": f"{loaded.name}.{event}: {exc}"})
    return problems


# -- status --------------------------------------------------------------------


#: Why a plugin is not actually running, by name.
#:
#: `status()` used to describe the checkout on disk and nothing else, so a
#: plugin whose import raised looked exactly like one running fine: version,
#: commit, tool list, "installed". The only trace was a line in a log file, and
#: the visible symptom was a component reporting "sidecar not connected" --
#: which is what happens *because* the plugin never loaded, not why.
#:
#: Two ways to be installed and not running, and they need different answers:
#: an import that failed (fix the plugin) and an update applied after the
#: Gateway loaded the old code (restart Marvi).
_not_running: dict[str, str] = {}


def note_loaded(name: str) -> None:
    _not_running.pop(name, None)


def note_not_running(name: str, why: str) -> None:
    _not_running[name] = why


def not_running(name: str) -> str:
    """Why this plugin is not live, or "" if it is."""
    return _not_running.get(name, "")


def status(repo_root: Path) -> list[dict[str, Any]]:
    """Every known plugin, whether it is installed, and at what version."""
    rows = []
    for source in sources(repo_root):
        directory = install_dir(source.name)
        row: dict[str, Any] = {
            "name": source.name,
            "title": source.title,
            "why": source.why,
            "repo": source.repo,
            "ref": source.ref,
            "installed": installed(source.name),
            "version": "",
            "commit": "",
            "tools": [],
            "detail": "not installed",
            "supported": True,
            #: Loaded and live in this Gateway, as opposed to merely present.
            "running": installed(source.name),
        }
        if row["installed"]:
            try:
                manifest = read_manifest(directory)
                row["version"] = manifest.version
                row["tools"] = list(manifest.provides_tools)
                supported, why = manifest.runs_here()
                row["supported"] = supported
                row["detail"] = "installed" if supported else why
            except PluginError as exc:
                row["detail"] = str(exc)
                row["supported"] = False
            try:
                row["commit"] = _git(["rev-parse", "--short", "HEAD"], cwd=directory, timeout=15)
            except (PluginError, OSError, subprocess.TimeoutExpired):
                row["commit"] = "unknown"
            if why := _not_running.get(source.name):
                row["running"] = False
                row["detail"] = why
        rows.append(row)
    return rows


# -- bridging a plugin's tools into the router ---------------------------------

#: JSON Schema types, as the router's argument types.
_SCHEMA_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}

#: What a guard is handed, and what it may raise. Marvi supplies these; a plugin
#: cannot. See `room.sleep_guard`.
Guard = Callable[[str, dict[str, Any]], None]


def _argument_types(schema: dict[str, Any]) -> tuple[dict[str, type], dict[str, type]]:
    """Split a JSON Schema's properties into required and optional, with types."""
    parameters = schema.get("parameters") or {}
    properties = parameters.get("properties") or {}
    required = set(parameters.get("required") or ())
    needed: dict[str, type] = {}
    optional: dict[str, type] = {}
    for name, definition in properties.items():
        declared = (definition or {}).get("type")
        # An unknown or union type is accepted as-is rather than guessed at; the
        # plugin validates its own arguments and the router still records them.
        python_type = _SCHEMA_TYPES.get(declared if isinstance(declared, str) else "", object)
        (needed if name in required else optional)[name] = python_type
    return needed, optional


def bridge_tools(
    registry: Any,
    loaded: LoadedPlugin,
    guard: Guard | None = None,
    read_only: frozenset[str] = frozenset(),
    skip: frozenset[str] = frozenset(),
) -> list[str]:
    """Register a plugin's requested tools with Marvi's router.

    Three rules, and the first two are why this is not a loop over `tools`:

    **A built-in wins.** A plugin cannot replace a tool Marvi already
    registered — that would let installing a plugin silently redefine what an
    existing tool does.

    **Marvi's guard runs first.** A plugin's own handler enforces whatever the
    plugin's author decided; it knows nothing about Marvi's rules. The room's
    sleep rule — only switching a light off, and YOLO cannot override it — lives
    in `room.py` and is applied *around* the plugin's handler, so bridging
    cannot open a path around it. A guard that raises stops the call.

    **Confirmation is the default.** `sensitive=True` unless the tool is named
    in `read_only`, which Marvi supplies and the plugin cannot influence. A
    plugin asking for something unconfirmed does not get it.

    `skip` is the same rule as the first one, for a plugin tool that duplicates
    a built-in under a different name. "A built-in wins" can only be enforced
    automatically when the two agree on the name, and `smart_room_state` and
    `room_state` do the same thing while agreeing on nothing.
    """
    from .tools import ToolSpec, UnknownToolError

    def already_registered(name: str) -> bool:
        # `get` raises rather than returning None for an unknown tool.
        try:
            registry.get(name)
        except UnknownToolError:
            return False
        return True

    registered = []
    for request in loaded.context.tools:
        if request.name in skip:
            log.info(
                "plugin tool not bridged; Marvi has her own",
                extra={"marvi_plugin": loaded.name, "marvi_tool": request.name},
            )
            continue
        if already_registered(request.name):
            log.info(
                "plugin tool not bridged; Marvi already has that name",
                extra={"marvi_plugin": loaded.name, "marvi_tool": request.name},
            )
            continue

        needed, optional = _argument_types(request.schema)
        description = str(request.schema.get("description") or request.name).strip()

        def call(_request: ToolRequest = request, **arguments: Any) -> Any:
            if guard is not None:
                # Before the plugin sees it. A guard raising is a refusal.
                guard(_request.name, arguments)
            # Plugin handlers take one dict, not keyword arguments. Their
            # bridge returns JSON text, so a normal Python return does not mean
            # the sidecar action succeeded. Promote an explicit plugin failure
            # into the Gateway's authoritative failed status.
            response = _request.handler(arguments)
            payload: Any = response
            if isinstance(response, str):
                try:
                    payload = json.loads(response)
                except json.JSONDecodeError:
                    payload = response
            if isinstance(payload, dict) and payload.get("success") is False:
                raise RuntimeError(str(payload.get("error") or f"{_request.name} failed"))
            return response

        registry.register(
            ToolSpec(
                name=request.name,
                description=description[:200],
                arguments=needed,
                optional=optional,
                sensitive=request.name not in read_only,
                handler=call,
            )
        )
        registered.append(request.name)

    log.info(
        "bridged plugin tools",
        extra={
            "marvi_plugin": loaded.name,
            "marvi_tools": ", ".join(registered) or "none",
        },
    )
    return registered


def context_lines(loaded: list[LoadedPlugin], limit: int = 240) -> list[str]:
    """One short line per plugin, for the system prompt.

    Smart Room uses this for bounded presence, location, mode, and light state.
    A future camera-owning sidecar can add a compact vision block to the same
    public context contract without exposing frames or private implementation.

    Bounded and defensive: this runs on the prompt path, so a plugin that is slow
    or throws must not take a turn down with it, and a plugin that returns an
    essay must not eat the identity budget.
    """
    lines = []
    for plugin in loaded:
        for name, provider in plugin.context.context_providers.items():
            try:
                value = provider()
            except Exception as exc:
                log.warning("context provider %s.%s failed: %s", plugin.name, name, exc)
                continue
            if not value:
                # None is the documented "nothing to say" answer, not an error.
                continue
            text = str(value).strip().replace("\n", " ")
            if text:
                lines.append(text[:limit])
    return lines
