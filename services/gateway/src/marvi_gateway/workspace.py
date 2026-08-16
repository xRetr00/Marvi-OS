"""File, terminal, and process tools.

These are the tools that can actually damage the machine, so the boundary is
narrow and boring on purpose:

* every path is resolved and must land inside one allowlisted root, so `..`,
  absolute paths, and symlinks pointing outward are all refused by the same
  check rather than by pattern-matching the string;
* reads are ungated but enveloped, because a file can contain instructions
  aimed at whoever reads it next;
* writes, deletes, command execution, and killing a process are sensitive, so
  they inherit the Phase 4 confirmation token and audit trail;
* nothing here runs without an explicitly configured root. Absent
  configuration means the tools refuse, not that they default to the whole
  disk.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .untrusted import wrap_external

MAX_READ_BYTES = 200_000
MAX_OUTPUT_CHARS = 20_000
DEFAULT_COMMAND_TIMEOUT = 60
MAX_COMMAND_TIMEOUT = 600


class WorkspaceRefusedError(Exception):
    """The request left the allowlisted root, or no root is configured."""


class CommandFailedError(Exception):
    pass


def default_root() -> Path | None:
    configured = os.environ.get("MARVI_WORKSPACE_ROOT", "").strip()
    return Path(configured).expanduser().resolve() if configured else None


class Workspace:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root.expanduser().resolve() if root else default_root()

    def available(self) -> bool:
        return self.root is not None and self.root.is_dir()

    def resolve(self, relative: str) -> Path:
        """Resolve inside the root or refuse.

        `Path.resolve()` collapses `..` and follows symlinks first, so the
        containment check sees where the path really lands.
        """
        if self.root is None:
            raise WorkspaceRefusedError(
                "No workspace root configured. Set MARVI_WORKSPACE_ROOT."
            )
        candidate = (self.root / relative).expanduser()
        try:
            resolved = candidate.resolve()
        except OSError as exc:
            raise WorkspaceRefusedError(f"could not resolve {relative}") from exc
        if resolved != self.root and self.root not in resolved.parents:
            raise WorkspaceRefusedError(
                f"{relative} resolves outside the workspace root; refused"
            )
        return resolved

    # -- files ------------------------------------------------------------

    def list_dir(self, relative: str = ".") -> list[dict[str, Any]]:
        target = self.resolve(relative)
        if not target.is_dir():
            raise WorkspaceRefusedError(f"{relative} is not a directory")
        entries = []
        for child in sorted(target.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
            entries.append(
                {
                    "name": child.name,
                    "path": str(child.relative_to(self.root)).replace("\\", "/"),
                    "directory": child.is_dir(),
                    "bytes": child.stat().st_size if child.is_file() else None,
                }
            )
        return entries

    def read(self, relative: str) -> dict[str, Any]:
        target = self.resolve(relative)
        if not target.is_file():
            raise WorkspaceRefusedError(f"{relative} is not a file")
        raw = target.read_bytes()[:MAX_READ_BYTES]
        return {
            "path": relative,
            "truncated": target.stat().st_size > MAX_READ_BYTES,
            "text": raw.decode("utf-8", "replace"),
        }

    def write(self, relative: str, content: str) -> dict[str, Any]:
        target = self.resolve(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        target.write_text(content, encoding="utf-8")
        return {"path": relative, "bytes": len(content.encode("utf-8")), "overwrote": existed}

    def delete(self, relative: str) -> dict[str, Any]:
        target = self.resolve(relative)
        if target == self.root:
            raise WorkspaceRefusedError("refusing to delete the workspace root")
        if not target.exists():
            return {"path": relative, "deleted": False}
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"path": relative, "deleted": True}

    # -- terminal ---------------------------------------------------------

    def run(self, command: str, timeout: int = DEFAULT_COMMAND_TIMEOUT) -> dict[str, Any]:
        if self.root is None:
            raise WorkspaceRefusedError("No workspace root configured.")
        if not command.strip():
            raise WorkspaceRefusedError("empty command")
        seconds = max(1, min(int(timeout), MAX_COMMAND_TIMEOUT))
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=seconds,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired as exc:
            raise CommandFailedError(f"command timed out after {seconds}s") from exc
        return {
            "command": command,
            "exit_code": completed.returncode,
            "stdout": (completed.stdout or "")[:MAX_OUTPUT_CHARS],
            "stderr": (completed.stderr or "")[:MAX_OUTPUT_CHARS],
        }

    # -- processes --------------------------------------------------------

    def processes(self, contains: str = "") -> list[dict[str, Any]]:
        """Best-effort listing using the platform's own tool; no new dependency.

        ponytail: capped at 200 rows, so an unfiltered listing on a busy machine
        is a sample, not an inventory. Pass `contains` when you are looking for
        something specific.
        """
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/fo", "csv", "/nh"],
                capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace",
            )
            rows = []
            for line in (result.stdout or "").splitlines():
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) < 2:
                    continue
                name, pid = parts[0].strip('"'), parts[1]
                if contains and contains.lower() not in name.lower():
                    continue
                rows.append({"pid": int(pid) if pid.isdigit() else None, "name": name})
            return rows[:200]

        result = subprocess.run(
            ["ps", "-eo", "pid,comm"],
            capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace",
        )
        rows = []
        for line in (result.stdout or "").splitlines()[1:]:
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            if contains and contains.lower() not in parts[1].lower():
                continue
            rows.append({"pid": int(parts[0]), "name": parts[1]})
        return rows[:200]

    def kill(self, pid: int) -> dict[str, Any]:
        if pid == os.getpid():
            raise WorkspaceRefusedError("refusing to kill the Gateway itself")
        try:
            os.kill(pid, 9)
        except OSError as exc:
            raise CommandFailedError(f"could not stop process {pid}: {exc}") from exc
        return {"pid": pid, "stopped": True}


def register_workspace_tools(registry, workspace: Workspace) -> None:
    from .tools import ToolSpec

    def file_list(path: str = ".") -> dict[str, Any]:
        return {"entries": workspace.list_dir(path)}

    def file_read(path: str) -> dict[str, Any]:
        # A file can carry instructions aimed at whoever reads it next.
        return wrap_external(f"file:{path}", workspace.read(path)["text"]).model_dump()

    def file_write(path: str, content: str) -> dict[str, Any]:
        return workspace.write(path, content)

    def file_delete(path: str) -> dict[str, Any]:
        return workspace.delete(path)

    def terminal_run(command: str, timeout: int = DEFAULT_COMMAND_TIMEOUT) -> dict[str, Any]:
        result = workspace.run(command, timeout)
        return {
            "exit_code": result["exit_code"],
            "output": wrap_external(
                f"terminal:{result['command'][:60]}",
                {"stdout": result["stdout"], "stderr": result["stderr"]},
            ).model_dump(),
        }

    def process_list(contains: str = "") -> dict[str, Any]:
        return {"processes": workspace.processes(contains)}

    def process_stop(pid: int) -> dict[str, Any]:
        return workspace.kill(pid)

    for spec in (
        ToolSpec(
            name="file_list", description="List files in the workspace",
            arguments={}, optional={"path": str}, sensitive=False, handler=file_list,
        ),
        ToolSpec(
            name="file_read", description="Read a file from the workspace",
            arguments={"path": str}, sensitive=False, handler=file_read,
        ),
        ToolSpec(
            name="file_write", description="Write a file in the workspace",
            arguments={"path": str, "content": str}, sensitive=True, handler=file_write,
        ),
        ToolSpec(
            name="file_delete", description="Delete a file in the workspace",
            arguments={"path": str}, sensitive=True, handler=file_delete,
        ),
        ToolSpec(
            name="terminal_run", description="Run a command in the workspace",
            arguments={"command": str}, optional={"timeout": int},
            sensitive=True, handler=terminal_run,
        ),
        ToolSpec(
            name="process_list", description="List running processes",
            arguments={}, optional={"contains": str}, sensitive=False, handler=process_list,
        ),
        ToolSpec(
            name="process_stop", description="Stop a running process",
            arguments={"pid": int}, sensitive=True, handler=process_stop,
        ),
    ):
        registry.register(spec)
