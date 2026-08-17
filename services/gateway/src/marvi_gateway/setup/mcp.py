"""Adding MCP servers.

**An MCP server is not data. It is a process that runs code on this machine.**
Downloading a model is a bandwidth decision; adding an MCP server is a trust
decision, and the two must not feel the same.

So adding one is a two-step flow by construction: `prepare` returns exactly what
will be executed and refuses to write anything, and `add` will not proceed
without the confirmation token that `prepare` issued for that exact command.
There is no single call that installs a server.

## The format is everybody's format

The config shape is the one Claude Desktop, Claude Code, Cursor and VS Code all
use — `command`, `args`, `env`, over stdio:

    {"mcpServers": {"name": {"command": "npx", "args": ["-y", "pkg"]}}}

Marvi reads and writes that, so a server someone already has configured
elsewhere can be pasted in, and one added here can be copied out. Inventing a
private format would buy nothing.

Two conventions worth encoding rather than rediscovering:

* `npx` needs `-y`, or it stops to ask about installing the package and the
  handshake times out with no explanation.
* Python servers over stdio need `PYTHONUNBUFFERED=1`, or output sits in a
  buffer and the handshake times out the same way.

## What Marvi will not do

* Run a command it was not shown. The token binds to the exact argv.
* Install from a URL it found itself. The source is always something the user
  named.
* Give an MCP server a private path to tools. Its tools enter through the
  existing router, so they inherit confirmation and audit (ADR-016).
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..logs import get_logger
from ..paths import mcp_config

log = get_logger("setup")

HANDSHAKE_TIMEOUT = 25.0

#: Runners Marvi knows how to sanity-check. Anything else is allowed but is
#: reported as unrecognised, because "we have never seen this" is useful to
#: know before saying yes.
KNOWN_RUNNERS = {
    "npx": "Node package runner",
    "uvx": "Python package runner",
    "node": "Node script",
    "python": "Python script",
    "docker": "container",
}


@dataclass
class Server:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True

    def argv(self) -> list[str]:
        return [self.command, *self.args]

    def display(self) -> str:
        """Exactly what will run, as a person would read it."""
        return " ".join(self.argv())

    def as_config(self) -> dict[str, Any]:
        entry: dict[str, Any] = {"command": self.command, "args": list(self.args)}
        if self.env:
            entry["env"] = dict(self.env)
        if not self.enabled:
            entry["disabled"] = True
        return entry


def normalise(name: str, command: str, args: list[str], env: dict[str, str]) -> Server:
    """Apply the conventions that are otherwise discovered by debugging."""
    args = list(args)
    env = dict(env)
    runner = Path(command).stem.lower()

    if runner == "npx" and "-y" not in args and "--yes" not in args:
        # Without this npx stops to ask, and the handshake times out with
        # nothing to explain why.
        args.insert(0, "-y")
    if runner in ("python", "python3", "uvx"):
        # Buffered stdout over stdio looks exactly like a hung server.
        env.setdefault("PYTHONUNBUFFERED", "1")
    return Server(name=name, command=command, args=args, env=env)


def read(path: Path | None = None) -> dict[str, Server]:
    target = path or mcp_config()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    servers: dict[str, Server] = {}
    for name, entry in (raw.get("mcpServers") or {}).items():
        if not isinstance(entry, dict) or not entry.get("command"):
            continue
        servers[name] = Server(
            name=name,
            command=str(entry["command"]),
            args=[str(a) for a in entry.get("args", [])],
            env={str(k): str(v) for k, v in (entry.get("env") or {}).items()},
            enabled=not entry.get("disabled", False),
        )
    return servers


def write(servers: dict[str, Server], path: Path | None = None) -> Path:
    target = path or mcp_config()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {"mcpServers": {name: s.as_config() for name, s in sorted(servers.items())}},
            indent=2,
        ),
        encoding="utf-8",
    )
    return target


# -- adding, in two steps ---------------------------------------------------------

#: Issued by `prepare`, spent by `add`. Single use, bound to one exact command.
_pending: dict[str, tuple[Server, str]] = {}


def prepare(
    name: str, command: str, args: list[str] | None = None, env: dict[str, str] | None = None
) -> dict[str, Any]:
    """Describe what would run. Writes nothing, starts nothing.

    The returned token is the only way to reach `add`, and it is bound to this
    exact argv — so what the user approves is what runs, with no room for the
    command to change in between.
    """
    server = normalise(name, command, list(args or []), dict(env or {}))
    runner = Path(server.command).stem.lower()
    resolved = shutil.which(server.command)

    token = secrets.token_urlsafe(16)
    _pending[token] = (server, server.display())

    warnings = []
    if runner not in KNOWN_RUNNERS:
        warnings.append(f"'{server.command}' is not a runner Marvi recognises.")
    if not resolved:
        warnings.append(
            f"'{server.command}' was not found on PATH; the server will not start."
        )
    if server.env:
        warnings.append(
            "Environment variables will be set for this process: "
            + ", ".join(sorted(server.env))
        )
    return {
        "token": token,
        "name": server.name,
        # The whole point: the exact command, in full, before anything happens.
        "command": server.display(),
        "resolved": resolved or "",
        "runner": KNOWN_RUNNERS.get(runner, "unrecognised"),
        "warnings": warnings,
        "notice": (
            "This runs a program on your machine with your permissions. Its "
            "tools go through Marvi's confirmation and audit like any other."
        ),
    }


def add(token: str, path: Path | None = None) -> dict[str, Any]:
    """Save a server that was prepared and approved."""
    pending = _pending.pop(token, None)
    if pending is None:
        # Either never prepared, already used, or the process restarted. All
        # three mean: show the command again and ask again.
        return {"ok": False, "detail": "that approval is not valid; start again"}
    server, approved_display = pending
    if server.display() != approved_display:
        return {"ok": False, "detail": "the command changed after approval"}

    servers = read(path)
    servers[server.name] = server
    write(servers, path)
    log.info(
        "added MCP server %s", server.name, extra={"marvi_command": server.display()}
    )
    return {"ok": True, "detail": f"added {server.name}", "command": server.display()}


def remove(name: str, path: Path | None = None) -> dict[str, Any]:
    servers = read(path)
    if name not in servers:
        return {"ok": False, "detail": f"no server named {name}"}
    del servers[name]
    write(servers, path)
    log.info("removed MCP server %s", name)
    return {"ok": True, "detail": f"removed {name}"}


def set_enabled(name: str, enabled: bool, path: Path | None = None) -> dict[str, Any]:
    """Turn a server off without forgetting how it was configured."""
    servers = read(path)
    if name not in servers:
        return {"ok": False, "detail": f"no server named {name}"}
    servers[name].enabled = enabled
    write(servers, path)
    return {"ok": True, "detail": f"{name} is {'enabled' if enabled else 'disabled'}"}


# -- testing ------------------------------------------------------------------------


def test(server: Server) -> dict[str, Any]:
    """Start the server, complete an MCP initialize, and stop it.

    A configured server that has never been spoken to is a server that will fail
    the first time it matters. This is the check that turns "saved" into
    "works", and it is why `add` is not the end of the flow.
    """
    if not shutil.which(server.command):
        return {"ok": False, "detail": f"{server.command} is not on PATH"}

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "Marvi OS", "version": "1"},
        },
    }
    try:
        finished = subprocess.run(  # noqa: S603 - argv the user explicitly approved
            server.argv(),
            input=json.dumps(request) + "\n",
            capture_output=True,
            text=True,
            timeout=HANDSHAKE_TIMEOUT,
            env={**os.environ, **server.env},
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "detail": (
                "no response within 25s. For npx check `-y`; for a Python "
                "server check PYTHONUNBUFFERED=1."
            ),
        }
    except OSError as exc:
        return {"ok": False, "detail": f"could not start: {exc}"}

    for line in (finished.stdout or "").splitlines():
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if isinstance(message, dict) and "result" in message:
            info = (message["result"] or {}).get("serverInfo") or {}
            return {
                "ok": True,
                "detail": f"handshake ok with {info.get('name', server.name)}",
                "server_info": info,
            }
        if isinstance(message, dict) and "error" in message:
            return {"ok": False, "detail": f"server refused: {message['error']}"}

    tail = (finished.stderr or "").strip().splitlines()[-2:]
    return {"ok": False, "detail": " / ".join(tail) or "no MCP response on stdout"}


def status(path: Path | None = None) -> list[dict[str, Any]]:
    """What is configured, without starting anything."""
    return [
        {
            "name": server.name,
            "command": server.display(),
            "enabled": server.enabled,
            "on_path": bool(shutil.which(server.command)),
            "env_keys": sorted(server.env),
        }
        for server in read(path).values()
    ]
