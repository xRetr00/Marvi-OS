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
import tempfile
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
    use_gpu: bool | None = None,
) -> Outcome:
    """Put a component in place, or confirm it already is.

    `use_gpu` only matters for GPU-sensitive components; None means "use the
    saved preference", which is what every caller that has not asked should
    pass.
    """
    if component.kind == "python":
        return _sync_project(component, repo_root, use_gpu=use_gpu)
    if component.kind == "command":
        return _run_command(component, repo_root)
    if component.source_type == "git":
        return _git_subdirectory(component, force=force)

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

    if component.binary:
        return _archive(component, http, progress, force=force)

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


def _archive(
    component: Component,
    http: Any,
    progress: Progress | None,
    force: bool = False,
) -> Outcome:
    """Download one archive, verify it, unpack it, and throw the archive away.

    LiveKit — and most released binaries — ship a zip or a tarball rather than
    the loose file the catalog's file map assumes. Keeping the archive after
    unpacking would double the disk cost of every binary component for nothing.
    """
    state = component.status()
    if state["installed"] and not force:
        return Outcome(component.name, True, "already installed", skipped=True)

    spec = component.files[0]
    target = component.target()
    staging = target.parent / f".{target.name}.unpacking"
    archive = staging / spec.path

    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        fetched = _download(
            component.url_for(spec), archive, spec, http, progress, component.name
        )
    except InstallError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        log.error("install of %s failed: %s", component.name, exc)
        return Outcome(component.name, False, str(exc), 0)

    try:
        # `shutil` picks the format from the suffix, and refuses anything it
        # does not know rather than leaving a half-unpacked directory.
        shutil.unpack_archive(str(archive), str(staging))
    except (OSError, ValueError, shutil.ReadError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return Outcome(component.name, False, f"could not unpack: {exc}", fetched)
    archive.unlink(missing_ok=True)

    # Releases vary on whether the payload sits at the archive root or inside a
    # versioned directory. Find the named file rather than encoding one
    # publisher's habit, then take everything beside it: a model archive is five
    # files that are useless apart, and a binary archive usually carries its
    # licence.
    found = next((f for f in staging.rglob(component.binary) if f.is_file()), None)
    if found is None:
        shutil.rmtree(staging, ignore_errors=True)
        return Outcome(
            component.name, False, f"{component.binary} is not in the archive", fetched
        )

    target.mkdir(parents=True, exist_ok=True)
    for item in found.parent.iterdir():
        destination = target / item.name
        if destination.exists():
            shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
        shutil.move(str(item), str(destination))
    if not is_windows():
        binary = target / component.binary
        binary.chmod(binary.stat().st_mode | 0o111)
    shutil.rmtree(staging, ignore_errors=True)

    log.info("installed %s", component.name, extra={"marvi_bytes": fetched})
    return Outcome(component.name, True, "downloaded, verified and unpacked", fetched)


def _sync_project(
    component: Component, repo_root: Path, use_gpu: bool | None = None
) -> Outcome:
    """Run `uv sync` for a Python service, on the right PyTorch index."""
    from ..doctor import find_uv
    from . import hardware

    uv = find_uv()
    if not uv:
        return Outcome(
            component.name, False,
            "uv is not installed; see Doctor for how to get it",
        )

    environment = dict(os.environ)
    note = ""
    if component.extra.get("gpu_sensitive"):
        # The mistake this exists to prevent: a CPU wheel on a GPU machine,
        # silent until someone wonders why the voice model is slow.
        decided = use_gpu
        if decided is None:
            decided = bool(hardware.question()["use_gpu"])
        environment["UV_TORCH_BACKEND"] = "cu130" if decided else "cpu"
        note = f" ({'GPU' if decided else 'CPU'} build)"
        log.info(
            "syncing %s for %s", component.name, "GPU" if decided else "CPU",
            extra={"marvi_torch_index": hardware.torch_index(decided)},
        )

    try:
        finished = subprocess.run(
            [uv, "sync", "--project", component.project],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=SYNC_TIMEOUT,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Outcome(component.name, False, f"uv sync failed: {exc}")
    if finished.returncode != 0:
        tail = (finished.stderr or finished.stdout or "").strip().splitlines()[-3:]
        return Outcome(component.name, False, " / ".join(tail) or "uv sync failed")
    return Outcome(component.name, True, f"dependencies synced{note}")


def _run_command(component: Component, repo_root: Path) -> Outcome:
    """Run an installer that owns its own download — Playwright, mostly.

    Run through `uv run` inside the owning project, so the tool is the one that
    project pinned rather than whatever happens to be on PATH.
    """
    from ..doctor import find_uv

    command = list(component.extra.get("run") or [])
    if not command:
        return Outcome(component.name, False, "no command in the manifest")
    if component.extra.get("windows_skip") and os.name == "nt":
        return Outcome(component.name, True, "not needed on Windows", skipped=True)

    uv = find_uv()
    if not uv:
        return Outcome(component.name, False, "uv is not installed")
    argv = [uv, "run", "--project", component.project or "services/gateway", *command]
    try:
        finished = subprocess.run(
            argv, cwd=repo_root, capture_output=True, text=True, timeout=SYNC_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Outcome(component.name, False, f"{' '.join(command)} failed: {exc}")
    if finished.returncode != 0:
        tail = (finished.stderr or finished.stdout or "").strip().splitlines()[-3:]
        return Outcome(component.name, False, " / ".join(tail) or "command failed")
    return Outcome(component.name, True, f"ran {' '.join(command)}")


def _git_subdirectory(component: Component, force: bool = False) -> Outcome:
    """Check out one subdirectory of a repository at a pinned revision.

    Some things are not published as downloadable files. The VibeVoice speaker
    voices are `.pt` files in a git repository and nowhere else, and without
    them the TTS model has nothing to sound like.

    Sparse checkout plus a shallow fetch of the one pinned commit. The obvious
    approach - a blobless clone then `git checkout <rev> -- <path>` - looks
    right and fails: with `--filter=blob:none` the blobs were never fetched and
    a path-limited checkout cannot lazily fetch them, so it dies with "unable to
    read sha1 file". Sparse checkout tells git what is wanted *before* the
    fetch, so only those blobs come down.
    """
    from ..doctor import find_uv  # noqa: F401 - kept for symmetry with the rest

    if not shutil.which("git"):
        return Outcome(
            component.name, False, "git is not installed; see Doctor for how to get it"
        )
    if not component.revision:
        # An unpinned checkout is different files tomorrow.
        return Outcome(component.name, False, "no revision pinned for this component")

    target = component.target()
    if component.status()["installed"] and not force:
        return Outcome(component.name, True, "already installed", skipped=True)

    staging = Path(tempfile.mkdtemp(prefix="marvi-git-"))
    try:
        repo = str(staging)
        for argv in (
            ["git", "init", "--quiet", repo],
            ["git", "-C", repo, "remote", "add", "origin", component.source_id],
            # --no-cone so an arbitrary path works, not just a top-level folder.
            ["git", "-C", repo, "sparse-checkout", "set", "--no-cone",
             component.subdirectory],
            # Depth 1 on the exact commit: no history, no other branches.
            ["git", "-C", repo, "fetch", "--depth", "1", "--quiet", "origin",
             component.revision],
            ["git", "-C", repo, "checkout", "--quiet", "FETCH_HEAD"],
        ):
            finished = subprocess.run(
                argv, capture_output=True, text=True, timeout=SYNC_TIMEOUT
            )
            if finished.returncode != 0:
                tail = (finished.stderr or "").strip().splitlines()[-2:]
                return Outcome(component.name, False, " / ".join(tail) or "git failed")

        source = staging / component.subdirectory
        wanted = sorted(source.glob(component.pattern)) if source.exists() else []
        if not wanted:
            return Outcome(
                component.name, False,
                f"nothing matching {component.pattern} in {component.subdirectory}",
            )

        target.mkdir(parents=True, exist_ok=True)
        for item in wanted:
            if item.is_file():
                shutil.copy2(item, target / item.name)
        log.info(
            "checked out %s", component.name,
            extra={"marvi_files": len(wanted), "marvi_revision": component.revision},
        )
        return Outcome(component.name, True, f"{len(wanted)} file(s) checked out")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Outcome(component.name, False, f"checkout failed: {exc}")
    finally:
        # A clone is throwaway; leaving one behind wastes a lot of disk.
        shutil.rmtree(staging, ignore_errors=True, onerror=None)


def command_installed(component: Component, repo_root: Path) -> bool:
    """Whether a command-kind component has already done its work."""
    from ..doctor import find_uv

    check = list(component.extra.get("check") or [])
    uv = find_uv()
    if not check or not uv:
        return False
    try:
        finished = subprocess.run(
            [uv, "run", "--project", component.project or "services/gateway", *check],
            cwd=repo_root, capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return finished.returncode == 0


def state_of(component: Component, repo_root: Path, deep: bool = True) -> dict[str, Any]:
    """A component's real state, including the kinds a file map cannot describe.

    `Component.status()` only knows about downloaded files, so it answered
    "nothing to verify" for every Python environment and every command — which
    is what `marvi models list` showed for five of nine components. That reads
    as "broken" and is really "this check was never written".
    """
    if component.kind == "python":
        marker = repo_root / (component.project or "") / ".venv"
        shared = repo_root / ".venv"
        if marker.is_dir() or shared.is_dir():
            return {"installed": True, "detail": "environment present", "problems": []}
        return {"installed": False, "detail": "not synced", "problems": []}
    if component.kind == "command":
        if is_windows() and component.extra.get("windows_skip"):
            return {"installed": True, "detail": "not needed on Windows", "problems": []}
        if not component.extra.get("check"):
            # Honest: running it again is cheap and idempotent, so there is
            # nothing to report except that nobody can tell from here.
            return {"installed": False, "detail": "cannot be checked; safe to re-run", "problems": []}
        if not deep:
            # `command_installed` shells out with a 60s timeout. Never on a
            # hot path.
            return {"installed": True, "detail": "not checked", "problems": []}
        if command_installed(component, repo_root):
            return {"installed": True, "detail": "present", "problems": []}
        return {"installed": False, "detail": "not installed", "problems": []}
    return component.status(deep=deep)


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
