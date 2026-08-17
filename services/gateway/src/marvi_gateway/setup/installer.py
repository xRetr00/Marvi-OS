"""Installing, verifying, and removing components.

Four properties, each earning its complexity:

* **Verified.** A file is not installed until its hash matches. Nothing is moved
  into place before that check passes, so a partial download can never be
  mistaken for a working install.
* **Resumable.** Model weights are gigabytes on a home connection. A download
  writes to `<name>.part` and asks for a `Range` on the way back, so an
  interruption costs the bytes since the last write rather than all of them.
* **Idempotent.** Running setup on a complete install verifies and says so. This
  is what makes `marvi setup` safe to run whenever, which is what makes people
  actually run it.
* **Reversible.** Everything lands under one root, and `remove` takes it away.

## Why the atomic move matters more than it looks

Writing straight to the final path means a crash mid-download leaves a file that
*looks* installed — right name, right place, wrong contents. Every later check
that trusts existence rather than hashing will be wrong, and the failure surfaces
somewhere unrelated. The `.part` file makes an incomplete download visibly
incomplete.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..logs import get_logger
from .catalog import Component, FileSpec, install_root

log = get_logger("setup")

CHUNK = 1024 * 1024
DOWNLOAD_TIMEOUT = 300.0
SYNC_TIMEOUT = 900.0

#: Called with (component, file path, bytes done, bytes total).
Progress = Callable[[str, str, int, int], None]


@dataclass
class Outcome:
    component: str
    ok: bool
    detail: str
    bytes_fetched: int = 0
    skipped: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "ok": self.ok,
            "detail": self.detail,
            "bytes_fetched": self.bytes_fetched,
            "skipped": self.skipped,
        }


class InstallError(Exception):
    pass


def _download(
    url: str,
    destination: Path,
    spec: FileSpec,
    http: Any = None,
    progress: Progress | None = None,
    component: str = "",
) -> int:
    """Fetch one file, resuming if a part is already on disk."""
    import httpx

    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + ".part")
    already = part.stat().st_size if part.exists() else 0

    # Only resume when the server can be told where to continue from, and only
    # when what is on disk is plausibly a prefix of the real file.
    headers = {}
    if already and spec.size and already < spec.size:
        headers["Range"] = f"bytes={already}-"
    elif already:
        part.unlink()
        already = 0

    client = http or httpx.Client(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True)
    fetched = 0
    try:
        with client.stream("GET", url, headers=headers) as response:
            if response.status_code == 416:
                # The range is past the end: what is on disk is not a prefix.
                part.unlink(missing_ok=True)
                raise InstallError("stale partial download; retry to start over")
            if response.status_code not in (200, 206):
                raise InstallError(f"HTTP {response.status_code} fetching {spec.path}")
            if response.status_code == 200 and already:
                # No resume offered, so start again rather than appending to a
                # prefix the server is not honouring.
                already = 0
            mode = "ab" if response.status_code == 206 and already else "wb"
            with part.open(mode) as handle:
                for chunk in response.iter_bytes(CHUNK):
                    handle.write(chunk)
                    fetched += len(chunk)
                    if progress:
                        progress(component, spec.path, already + fetched, spec.size)
    except InstallError:
        raise
    except Exception as exc:
        raise InstallError(f"could not fetch {spec.path}: {exc}") from exc
    finally:
        if http is None:
            client.close()

    ok, reason = FileSpec(part.name, spec.size, spec.sha256).verify(part.parent)
    if not ok:
        # Never move a file that failed its check into the place something else
        # will trust. Keep the part for the next resume unless it is corrupt.
        if reason == "hash mismatch":
            part.unlink(missing_ok=True)
        raise InstallError(f"{spec.path}: {reason}")

    part.replace(destination)
    return fetched


def install(
    component: Component,
    repo_root: Path,
    http: Any = None,
    progress: Progress | None = None,
    force: bool = False,
) -> Outcome:
    """Put a component in place, or confirm it already is."""
    if component.kind == "python":
        return _sync_project(component, repo_root)

    if not component.files:
        return Outcome(
            component.name, True,
            "nothing to download; this component is described but not yet fetchable",
            skipped=True,
        )

    state = component.status()
    if state["installed"] and not force:
        # Running setup on a complete install must cost nothing and say so.
        return Outcome(component.name, True, "already installed", skipped=True)

    base = component.target()
    fetched = 0
    for spec in component.files:
        ok, _reason = spec.verify(base)
        if ok and not force:
            continue
        try:
            fetched += _download(
                component.url_for(spec), base / spec.path, spec, http, progress,
                component.name,
            )
        except InstallError as exc:
            log.error("install of %s failed: %s", component.name, exc)
            return Outcome(component.name, False, str(exc), fetched)

    final = component.status()
    if not final["installed"]:
        return Outcome(component.name, False, final["detail"], fetched)
    log.info("installed %s", component.name, extra={"marvi_bytes": fetched})
    return Outcome(component.name, True, "installed and verified", fetched)


def _sync_project(component: Component, repo_root: Path) -> Outcome:
    """Run `uv sync` for a Python service."""
    from ..doctor import find_uv

    uv = find_uv()
    if not uv:
        return Outcome(
            component.name, False,
            "uv is not installed; see Doctor for how to get it",
        )
    try:
        finished = subprocess.run(
            [uv, "sync", "--project", component.project],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=SYNC_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Outcome(component.name, False, f"uv sync failed: {exc}")
    if finished.returncode != 0:
        tail = (finished.stderr or finished.stdout or "").strip().splitlines()[-3:]
        return Outcome(component.name, False, " / ".join(tail) or "uv sync failed")
    return Outcome(component.name, True, "dependencies synced")


def verify(component: Component) -> Outcome:
    state = component.status()
    return Outcome(component.name, bool(state["installed"]), state["detail"])


def remove(component: Component) -> Outcome:
    """Delete a component. Nothing lives outside the install root, so this is
    honest rather than approximate."""
    target = component.target()
    root = install_root().resolve()
    try:
        resolved = target.resolve()
    except OSError:
        return Outcome(component.name, False, "could not resolve the install path")

    if root not in resolved.parents and resolved != root:
        # A manifest should never point outside the tree Marvi owns, and if one
        # does, deleting it is the wrong response.
        return Outcome(
            component.name, False,
            f"refusing to delete {resolved}, which is outside {root}",
        )
    if not resolved.exists():
        return Outcome(component.name, True, "not installed", skipped=True)
    try:
        shutil.rmtree(resolved)
    except OSError as exc:
        return Outcome(component.name, False, f"could not remove: {exc}")
    log.info("removed %s", component.name)
    return Outcome(component.name, True, "removed")


def plan(components: list[Component]) -> dict[str, Any]:
    """What a setup run would do, before it does it.

    Size matters here: a first run that downloads several gigabytes without
    saying so is a bad first run.
    """
    missing = [c for c in components if not c.status()["installed"]]
    return {
        "install": [
            {
                "name": c.name,
                "title": c.title,
                "why": c.why,
                "bytes": c.bytes_total,
                "needed_for": list(c.needed_for),
            }
            for c in missing
        ],
        "already_installed": [
            c.name for c in components if c.status()["installed"]
        ],
        "bytes_total": sum(c.bytes_total for c in missing),
    }


def disk_space_for(components: list[Component]) -> tuple[bool, str]:
    """Refuse before starting rather than filling the disk halfway through."""
    needed = sum(c.bytes_total for c in components if not c.status()["installed"])
    if not needed:
        return True, "nothing to download"
    root = install_root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        free = shutil.disk_usage(root).free
    except OSError:
        return True, "could not measure free space"
    # A margin, because a disk that ends up completely full breaks more than
    # this install.
    if free < needed * 1.2:
        return False, (
            f"needs {needed / 1024**3:.1f} GB and only "
            f"{free / 1024**3:.1f} GB is free"
        )
    return True, f"{needed / 1024**3:.1f} GB to download"


def env_overrides() -> dict[str, str]:
    """Where installs land, so the rest of Marvi can find them without guessing."""
    root = install_root()
    return {
        "MARVI_MODEL_ROOT": str(root / "models"),
        "MARVI_RUNTIME_ROOT": str(root / "runtime"),
    }


def is_windows() -> bool:
    return os.name == "nt"
