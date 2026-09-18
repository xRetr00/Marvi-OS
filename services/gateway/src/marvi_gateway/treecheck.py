"""A snapshot of the whole workspace, taken before a command that can destroy it.

The file tools have kept a copy of what they were about to change since
`checkpoints.py` was written. `terminal_run` had nothing: one
`Remove-Item -Recurse src`, one `git reset --hard`, one `>` in the wrong place,
and the work was gone with no copy anywhere.

This is the other half. Before a command that looks destructive, the workspace
is committed to a **shadow repository** -- a `GIT_DIR` that lives in Marvi's own
data directory, pointed at the workspace as its work tree. The user's own `.git`
is never touched, never read and never written; `git status` in their project
shows nothing new, and a project that is not a repository at all still gets
snapshots.

Three things this buys that copying files could not:

* **The whole tree, cheaply.** Git stores only what changed, so a snapshot
  before every destructive command costs kilobytes rather than a copy of the
  project each time.
* **`.gitignore` for free.** `node_modules`, `.venv` and build output are
  skipped because the workspace already says to skip them.
* **A real diff.** "What would restoring change" is `git diff`, not a guess.

Hermes Agent's checkpoint manager is the design reference (MIT): one shared
shadow store, the project's own repository left alone. No code is taken.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import paths
from .logs import get_logger

log = get_logger("gateway")

#: How long any git call may take. A snapshot that hangs would hang the command
#: it was protecting, which is worse than having no snapshot.
TIMEOUT = 45

#: Snapshots kept per workspace. Older commits are left unreferenced in the
#: store and reclaimed by `git gc`; the *list* is what is capped.
KEEP = 60

#: Commands that can lose work, by the word that starts them or a fragment that
#: gives them away. Matched case-insensitively against the command line.
#:
#: Deliberately generous: a snapshot before a harmless command costs a few
#: kilobytes, and missing one costs the work. The cost of a false positive and
#: the cost of a false negative are not remotely symmetrical here.
DESTRUCTIVE = (
    # POSIX-ish
    r"\brm\b", r"\brmdir\b", r"\bmv\b", r"\bdd\b", r"\bshred\b", r"\btruncate\b",
    r"\bsed\b\s+-i", r"\bfind\b.*-delete", r"\bxargs\b.*\brm\b",
    # PowerShell
    r"\bremove-item\b", r"\bri\b\s", r"\bmove-item\b", r"\bset-content\b",
    r"\bout-file\b", r"\bclear-content\b", r"\bnew-item\b.*-force",
    # cmd
    r"\bdel\b", r"\berase\b", r"\bmove\b", r"\brd\b", r"\bformat\b",
    # git's own destructive verbs
    r"\bgit\b\s+reset\b.*--hard", r"\bgit\b\s+clean\b", r"\bgit\b\s+checkout\b\s+--",
    r"\bgit\b\s+restore\b", r"\bgit\b\s+branch\b\s+-D",
    # a redirect that replaces a file
    r"[^>|]>[^>|]",
)

_PATTERN = re.compile("|".join(DESTRUCTIVE), re.IGNORECASE)
_lock = threading.Lock()


def looks_destructive(command: str) -> bool:
    """Whether this command could lose work. Generous on purpose."""
    return bool(_PATTERN.search(command or ""))


def store() -> Path:
    """Where the shadow repositories live. Never inside a user's project."""
    return paths.root() / "checkpoints" / "store"


def _git_dir(root: Path) -> Path:
    """One shadow repository per workspace, named for the path it shadows."""
    from hashlib import sha256

    stamp = sha256(str(root.resolve()).lower().encode("utf-8")).hexdigest()[:16]
    return store() / f"{root.name}-{stamp}.git"


def available() -> bool:
    return shutil.which("git") is not None


def _run(git_dir: Path, root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """One git call against the shadow repository and the real work tree."""
    environment = {
        **os.environ,
        "GIT_DIR": str(git_dir),
        "GIT_WORK_TREE": str(root),
        # The snapshot is Marvi's, not the user's, and must never inherit a
        # signing key, a hook or a global template that would make it theirs.
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": str(store()),
        "USERPROFILE": str(store()),
        "GIT_AUTHOR_NAME": "Marvi",
        "GIT_AUTHOR_EMAIL": "marvi@localhost",
        "GIT_COMMITTER_NAME": "Marvi",
        "GIT_COMMITTER_EMAIL": "marvi@localhost",
    }
    return subprocess.run(
        ["git", *args],
        env=environment,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        check=check,
        cwd=str(root),
    )


def _prepare(root: Path) -> Path | None:
    """The shadow repository for this workspace, created on first use."""
    if not available():
        return None
    git_dir = _git_dir(root)
    if (git_dir / "HEAD").exists():
        return git_dir
    git_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run(git_dir, root, "init", "--quiet", "--bare", str(git_dir))
        # `core.excludesFile` off: the user's global ignore rules are theirs,
        # and a snapshot that silently skipped files because of a setting in
        # their home directory would be a restore that silently loses them.
        _run(git_dir, root, "config", "core.excludesFile", "")
        _run(git_dir, root, "config", "gc.auto", "256")
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("could not prepare a snapshot store: %s", str(exc)[:200])
        return None
    return git_dir


def snapshot(root: Path, why: str) -> dict[str, Any] | None:
    """Commit the workspace as it is now. None when there is nothing to keep.

    Never raises: a snapshot that failed must not stop the command it was
    taken before. The caller says so in its result instead.
    """
    if root is None or not Path(root).is_dir():
        return None
    root = Path(root)
    with _lock:
        git_dir = _prepare(root)
        if git_dir is None:
            return None
        try:
            _run(git_dir, root, "add", "--all", check=False)
            committed = _run(
                git_dir, root, "commit", "--quiet", "--allow-empty",
                "-m", f"before: {why[:200]}", check=False,
            )
            if committed.returncode != 0:
                log.info("nothing to snapshot before %r", why[:80])
                return None
            found = _run(git_dir, root, "rev-parse", "--short", "HEAD")
        except (subprocess.SubprocessError, OSError) as exc:
            log.warning("could not snapshot the workspace: %s", str(exc)[:200])
            return None
    return {
        "id": found.stdout.strip(),
        "kind": "tree",
        "path": str(root),
        "action": "command",
        "why": why[:200],
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def listing(root: Path, limit: int = 20) -> list[dict[str, Any]]:
    """Recent whole-workspace snapshots, newest first."""
    if root is None or not Path(root).is_dir():
        return []
    git_dir = _git_dir(Path(root))
    if not (git_dir / "HEAD").exists():
        return []
    try:
        found = _run(
            git_dir, Path(root), "log", f"-{max(1, min(limit, KEEP))}",
            "--format=%h%x1f%cI%x1f%s", check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    rows = []
    for line in found.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        rows.append(
            {
                "id": parts[0],
                "kind": "tree",
                "path": str(root),
                "action": "command",
                "at": parts[1],
                "why": parts[2].removeprefix("before: "),
            }
        )
    return rows


def changed(root: Path, snapshot_id: str) -> list[str]:
    """Which files differ between that snapshot and the workspace now."""
    git_dir = _git_dir(Path(root))
    try:
        found = _run(git_dir, Path(root), "diff", "--name-only", snapshot_id, check=False)
    except (subprocess.SubprocessError, OSError):
        return []
    return [line.strip() for line in found.stdout.splitlines() if line.strip()]


def restore(root: Path, snapshot_id: str, relative: str = "") -> dict[str, Any]:
    """Put the workspace, or one file in it, back to a snapshot.

    A restore takes its own snapshot first, so undoing an undo is the same
    operation again -- the property the file-level checkpoints already have.
    """
    root = Path(root)
    git_dir = _git_dir(root)
    if not (git_dir / "HEAD").exists():
        raise FileNotFoundError("there are no workspace snapshots yet")
    before = snapshot(root, f"restore of {snapshot_id}")
    target = [relative] if relative else ["."]
    try:
        _run(git_dir, root, "checkout", snapshot_id, "--", *target)
    except subprocess.CalledProcessError as exc:
        raise FileNotFoundError(
            (exc.stderr or exc.stdout or "that snapshot does not have it").strip()[:200]
        ) from exc
    return {
        "restored": snapshot_id,
        "what": relative or "the whole workspace",
        "files": changed(root, snapshot_id),
        "previous_saved_as": (before or {}).get("id", ""),
    }
