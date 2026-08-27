"""File, terminal, and process tools.

These are the tools that can actually damage the machine, so the boundary is
narrow and boring on purpose:

* every path is resolved and then judged by `filepolicy`, which answers three
  questions separately -- how far reading may reach, how far writing may reach,
  and what is refused to both. `..`, absolute paths and symlinks pointing
  outward all go through that same check rather than through pattern-matching
  the string;
* reads are ungated but enveloped, because a file can contain instructions
  aimed at whoever reads it next;
* writes, deletes, command execution, and killing a process are sensitive, so
  they inherit the Phase 4 confirmation token and audit trail;
* the terminal runs in the workspace root and nowhere else, whatever the file
  scopes say. A shell is not a path and cannot be checked like one.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .filepolicy import Access, PathRefusedError
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
    return Access.from_env().root


#: A UTF-8 byte order mark. Windows editors write them, and a file that had one
#: and comes back without it reads as changed on its first line, every time.
BOM = b"\xef\xbb\xbf"


def _decode(raw: bytes) -> tuple[str, bytes]:
    """The text of a file, and the byte order mark to put back."""
    if raw.startswith(BOM):
        return raw[len(BOM) :].decode("utf-8", "replace"), BOM
    return raw.decode("utf-8", "replace"), b""


def _line_ending(text: str) -> str:
    """What this file uses. CRLF when it uses any, because a file with mixed
    endings is going to be fixed by whichever editor opens it next anyway."""
    return "\r\n" if "\r\n" in text else "\n"


def _retype(text: str, ending: str) -> str:
    """A model's newlines in the file's own dialect."""
    return text.replace("\r\n", "\n").replace("\n", ending)


class Workspace:
    def __init__(self, root: Path | None = None) -> None:
        self._pinned = root.expanduser().resolve() if root else None

    @property
    def access(self) -> Access:
        """The policy as it stands right now.

        Read per call rather than held, because the settings page writes these
        into the environment while the Gateway is running, and a value captured
        in `__init__` would mean every change needed a restart -- which is the
        shape of half the bugs already found in this codebase.
        """
        access = Access.from_env()
        if self._pinned is not None:
            access.root = self._pinned
        return access

    @property
    def root(self) -> Path | None:
        return self.access.root

    def available(self) -> bool:
        root = self.root
        return root is not None and root.is_dir()

    def resolve(self, relative: str, *, write: bool = False) -> Path:
        """Resolve and judge, or refuse.

        `write` is the whole point: reading and writing are separate settings,
        and a resolver that did not know which one it was being asked about
        could only ever enforce the stricter of the two.
        """
        try:
            return self.access.resolve(relative, write=write)
        except PathRefusedError as exc:
            raise WorkspaceRefusedError(str(exc)) from exc

    def shown(self, path: Path) -> str:
        """How a path is reported back: relative to the workspace when it is
        inside it, absolute when it is not. Both are unambiguous; a bare name
        for a file three directories outside the workspace is not."""
        root = self.root
        if root is not None:
            try:
                return str(path.relative_to(root)).replace("\\", "/")
            except ValueError:
                pass
        return str(path)

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
                    "path": self.shown(child),
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
            "path": self.shown(target),
            "truncated": target.stat().st_size > MAX_READ_BYTES,
            "text": _decode(raw)[0],
        }

    def write(self, relative: str, content: str) -> dict[str, Any]:
        target = self.resolve(relative, write=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        # `newline=""` so the bytes written are the bytes given. Python's text
        # mode translates every newline to CRLF on Windows, which silently
        # rewrites the line endings of any file Marvi touches -- a one-word
        # change arriving as a diff against every line in the file.
        with target.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        return {
            "path": self.shown(target),
            "bytes": len(content.encode("utf-8")),
            "overwrote": existed,
        }

    def edit(self, relative: str, old: str, new: str, replace_all: bool = False) -> dict[str, Any]:
        """Replace an exact passage in a file, leaving the rest byte for byte.

        The tool that was missing. Whole-file `write` was the only way to change
        a line, which means reproducing a file from memory to alter one word --
        unreliable from any model and impossible from a voice turn.

        Three things this does that a naive replace does not, each of them a
        real failure on Windows:

        * **Line endings.** Models send `old` and `new` with bare newlines
          because that is what JSON carries. A CRLF file then matches nothing,
          and "I could not find that text" is wrong in a way nobody can act on.
          Both sides are put into the file's own dialect before the search, and
          the file keeps its endings afterwards.
        * **Uniqueness.** An `old` that appears twice is ambiguous, and taking
          the first is how an edit lands in the wrong function. Refused, with
          the count, unless `replace_all` says otherwise.
        * **Already applied.** The commonest failure is re-sending an edit that
          landed. That is a no-op, not an error, and saying so is what stops a
          model re-reading and re-patching in a loop.
        """
        target = self.resolve(relative, write=True)
        if not target.is_file():
            raise WorkspaceRefusedError(f"{relative} is not a file")
        if not old:
            raise WorkspaceRefusedError("nothing to replace; `old` is empty")

        text, bom = _decode(target.read_bytes())
        ending = _line_ending(text)
        old_text, new_text = _retype(old, ending), _retype(new, ending)

        found = text.count(old_text)
        if found == 0:
            if new_text and new_text in text:
                # Success-shaped, deliberately: the file already says what the
                # caller wanted it to say.
                return {
                    "path": self.shown(target),
                    "changed": False,
                    "replacements": 0,
                    "note": "already applied; the file already contains the new text",
                }
            raise WorkspaceRefusedError(
                f"could not find that text in {self.shown(target)}. "
                "Read the file and copy the passage exactly, indentation included."
            )
        if found > 1 and not replace_all:
            raise WorkspaceRefusedError(
                f"that text appears {found} times in {self.shown(target)}. "
                "Include enough surrounding lines to make it unique, or pass replace_all."
            )

        count = found if replace_all else 1
        updated = text.replace(old_text, new_text, -1 if replace_all else 1)
        target.write_bytes(bom + updated.encode("utf-8"))

        # Read it back. A write that reports success while the bytes did not
        # land is the one failure a caller cannot detect for itself.
        verified, _ = _decode(target.read_bytes())
        if verified != updated:
            raise WorkspaceRefusedError(
                f"wrote {self.shown(target)} but reading it back gave something else"
            )
        return {
            "path": self.shown(target),
            "changed": True,
            "replacements": count,
            "bytes": len(updated.encode("utf-8")),
        }

    def delete(self, relative: str) -> dict[str, Any]:
        target = self.resolve(relative, write=True)
        if target == self.root:
            raise WorkspaceRefusedError("refusing to delete the workspace root")
        if not target.exists():
            return {"path": self.shown(target), "deleted": False}
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"path": self.shown(target), "deleted": True}

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

    def file_edit(
        path: str, old: str, new: str, replace_all: bool = False
    ) -> dict[str, Any]:
        return workspace.edit(path, old, new, replace_all)

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
            name="file_write",
            description="Create a file, or replace one entirely",
            arguments={"path": str, "content": str},
            sensitive=True,
            handler=file_write,
            describes={
                "path": "Relative to the workspace, or absolute when the "
                "write scope allows it.",
                "content": "The complete new contents. To change part of an "
                "existing file use file_edit instead -- rewriting a whole file "
                "to alter one line loses everything you did not remember.",
            },
        ),
        ToolSpec(
            name="file_edit",
            description="Change part of an existing file",
            arguments={"path": str, "old": str, "new": str},
            optional={"replace_all": bool},
            sensitive=True,
            handler=file_edit,
            describes={
                "path": "The file to change. It must already exist.",
                "old": "The exact text to replace, copied from the file "
                "including its indentation. It must appear exactly once "
                "unless replace_all is set; include surrounding lines to make "
                "it unique.",
                "new": "What to put there instead. An empty string deletes "
                "the passage.",
                "replace_all": "Replace every occurrence rather than refusing "
                "an ambiguous one. Default false.",
            },
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
