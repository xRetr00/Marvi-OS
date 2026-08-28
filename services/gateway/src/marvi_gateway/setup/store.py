"""The skill store.

Browsing and installing skills from GitHub repositories.

## Why a repo tree and not a marketplace API

Every skill catalogue worth using is ultimately a git repository of directories
containing `SKILL.md`, so that is what this reads: one call to the GitHub trees
API finds every skill in a repo, whatever the repo happens to call itself. No
vendor API to sign up for, no index format to agree on, and it works the day
someone points Marvi at their own private collection.

## The sources are the user's

`config/skill-sources.json` ships with a couple of well-known repositories and
is editable. **Marvi never installs from a source it discovered itself** — not
from a link in a web page, not from a suggestion in a model's output. The list
is the list.

## The catalogue is cached

Nine repositories, 488 skills, one HTTP request each for its frontmatter, in
order: **114 seconds**. The IPC call in front of it gives up at sixty, so the
Skills page could never finish loading -- and a fetch that never returned was
rendered as "still loading", forever, because absence of a result and a result
that has not arrived yet look identical to the code that draws the spinner.

Two changes. The frontmatter requests run concurrently, because they are
independent and waiting for 488 round trips one at a time is the whole cost.
And the result is written to disk with a timestamp: a skill catalogue changes
on the timescale of days, so the second
visit should not pay for the first.

## Browsing is not installing

`browse` and `fetch` only read. Installing goes through `skills.install_from`
after `skills.review`, so the instructions are shown and the `allowed-tools`
declaration is resolved against policy before anything is written. A store
button is a shortcut to that flow, never around it.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..logs import get_logger
from . import skills as skills_module

log = get_logger("setup")

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
TIMEOUT = 30.0
#: How long a cached catalogue is served without asking GitHub again. Days,
#: because that is how often a skill repository actually changes, and a stale
#: entry costs an install that fails rather than anything worse.
CACHE_HOURS = 12.0
#: Frontmatter requests in flight at once. GitHub's raw host is fine with this
#: and the alternative is 488 round trips end to end.
FETCHERS = 12
#: A skill is a handful of small text files. Anything larger is not a skill.
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 40


@dataclass(frozen=True)
class Source:
    name: str
    repo: str
    branch: str = "main"
    description: str = ""

    def tree_url(self) -> str:
        return f"{API}/repos/{self.repo}/git/trees/{self.branch}?recursive=1"

    def raw_url(self, path: str) -> str:
        return f"{RAW}/{self.repo}/{self.branch}/{path}"


@dataclass
class Listing:
    """One skill as it appears in the store, before anything is downloaded."""

    name: str
    description: str
    source: str
    repo: str
    path: str
    installed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "repo": self.repo,
            "path": self.path,
            "installed": self.installed,
        }


def sources(repo_root: Path) -> list[Source]:
    path = repo_root / "config" / "skill-sources.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    found = []
    for entry in raw.get("sources", []):
        try:
            found.append(
                Source(
                    name=str(entry["name"]),
                    repo=str(entry["repo"]),
                    branch=str(entry.get("branch", "main")),
                    description=str(entry.get("description", "")),
                )
            )
        except (KeyError, TypeError):
            log.warning("skipping a malformed skill source")
    return found


def browse(source: Source, http: Any = None) -> list[Listing]:
    """Every skill in a repository, with its description.

    Two calls per skill would be one per directory; instead the tree comes back
    in a single request and each `SKILL.md` is read only for its frontmatter.
    """
    import httpx

    client = http or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
    try:
        return _browse(source, client)
    finally:
        if http is None:
            client.close()


def _browse(source: Source, client: Any) -> list[Listing]:
    try:
        response = client.get(source.tree_url())
        if response.status_code != 200:
            log.warning("%s returned HTTP %s", source.repo, response.status_code)
            return []
        tree = response.json().get("tree", [])
        directories = [
            node["path"].rsplit("/", 1)[0]
            for node in tree
            if isinstance(node, dict) and str(node.get("path", "")).endswith("SKILL.md")
        ]

        def one(directory: str) -> Listing | None:
            skill_file = client.get(source.raw_url(f"{directory}/SKILL.md"))
            if skill_file.status_code != 200:
                return None
            try:
                skill = skills_module.parse(skill_file.text, source=source.repo)
            except skills_module.SkillError as exc:
                # A repo may hold drafts. Skip them rather than showing a broken
                # entry with an Install button.
                log.debug("skipping %s in %s: %s", directory, source.repo, exc)
                return None
            return _listing(source, directory, skill)

        # Concurrent because they are independent and there are hundreds of
        # them. Serial, nine repositories took nearly two minutes, which is
        # longer than anything in front of this is willing to wait.
        with ThreadPoolExecutor(max_workers=FETCHERS) as pool:
            listings = [row for row in pool.map(one, directories) if row is not None]
        return listings
    except Exception as exc:
        log.warning("could not browse %s: %s", source.repo, exc)
        return []


def _listing(source: Source, directory: str, skill: Any) -> Listing:
    return Listing(
        name=skill.name,
        description=skill.description,
        source=source.name,
        repo=source.repo,
        path=directory,
    )


def cache_path() -> Path:
    from ..paths import root

    return root() / "state" / "skill-catalogue.json"


def _cached(sources_named: list[str]) -> list[dict[str, Any]] | None:
    """The last catalogue, if it is recent and for the same sources.

    Keyed on the source list as well as the time: adding a repository and being
    shown yesterday's catalogue without it is a Skills page that appears to
    ignore the setting you just changed.
    """
    import time

    try:
        saved = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(saved, dict) or saved.get("sources") != sources_named:
        return None
    age = time.time() - float(saved.get("at") or 0)
    if age > CACHE_HOURS * 3600:
        return None
    rows = saved.get("rows")
    return rows if isinstance(rows, list) else None


def _save(sources_named: list[str], rows: list[dict[str, Any]]) -> None:
    import time

    target = cache_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"at": time.time(), "sources": sources_named, "rows": rows}),
            encoding="utf-8",
        )
    except OSError as exc:  # pragma: no cover - depends on the filesystem
        log.warning("could not cache the skill catalogue: %s", exc)


def catalogue(
    repo_root: Path, http: Any = None, *, refresh: bool = False
) -> list[dict[str, Any]]:
    """Every skill from every configured source, marked with what is installed.

    Served from the cache when there is a recent one. Building it means one
    tree request per repository and one frontmatter request per skill --
    hundreds of round trips, and nothing in front of this waits two minutes.
    """
    configured = sources(repo_root)
    named = [source.repo for source in configured]
    have = {skill.name for skill in skills_module.installed()}

    rows = None if refresh else _cached(named)
    if rows is None:
        rows = []
        for source in configured:
            rows.extend(listing.as_dict() for listing in browse(source, http))
        rows.sort(key=lambda row: row["name"])
        if rows:
            _save(named, rows)

    # Never cached: what is installed changes without the catalogue changing,
    # and a store that still says "Install" after you installed something is
    # a store nobody believes.
    for row in rows:
        row["installed"] = row["name"] in have
    return rows


def fetch(source: Source, path: str, http: Any = None) -> Path:
    """Download one skill into a temporary directory. Installs nothing.

    Returned so the caller can run `skills.review` on it and show the user what
    the skill actually says before it goes anywhere permanent.
    """
    import httpx

    client = http or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
    staging = Path(tempfile.mkdtemp(prefix="marvi-skill-"))
    try:
        response = client.get(source.tree_url())
        response.raise_for_status()
        wanted = [
            str(node["path"])
            for node in response.json().get("tree", [])
            if isinstance(node, dict)
            and str(node.get("path", "")).startswith(f"{path}/")
            and node.get("type") == "blob"
        ][:MAX_FILES]
        if not wanted:
            raise skills_module.SkillError(f"nothing found at {path}")

        for remote in wanted:
            relative = remote[len(path) + 1 :]
            # Only the layout the specification defines. An unexpected path is
            # not copied, and one containing .. is not written at all.
            top = relative.split("/", 1)[0]
            if ".." in relative or (
                "/" in relative and top not in skills_module.ALLOWED_SUBDIRECTORIES
            ):
                continue
            blob = client.get(source.raw_url(remote))
            if blob.status_code != 200 or len(blob.content) > MAX_FILE_BYTES:
                continue
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(blob.content)

        # The directory must be named for the skill, because the spec requires
        # the folder and the `name` field to match.
        skill = skills_module.parse(
            (staging / skills_module.SKILL_FILE).read_text(encoding="utf-8"),
            source=source.repo,
        )
        named = staging.parent / f"marvi-skill-{skill.name}"
        if named.exists():
            shutil.rmtree(named)
        staging.rename(named)
        return named
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        if http is None:
            client.close()


def review_remote(repo_root: Path, repo: str, path: str, registry: Any = None,
                  http: Any = None) -> dict[str, Any]:
    """Fetch a skill and describe it, without installing it."""
    source = next((s for s in sources(repo_root) if s.repo == repo), None)
    if source is None:
        # Never install from a source Marvi found itself; the list is the list.
        return {"ok": False, "detail": f"{repo} is not a configured skill source"}
    try:
        staged = fetch(source, path, http)
        skill = skills_module.read_skill(staged)
    except (skills_module.SkillError, OSError) as exc:
        return {"ok": False, "detail": str(exc)}
    reviewed = skills_module.review(skill, registry)
    reviewed["ok"] = True
    reviewed["staged"] = str(staged)
    return reviewed


def install_reviewed(staged: str) -> dict[str, Any]:
    """Install a skill that was fetched and shown. Cleans up the staging copy."""
    directory = Path(staged)
    if not directory.exists() or not directory.name.startswith("marvi-skill-"):
        return {"ok": False, "detail": "that download has expired; browse again"}
    try:
        return skills_module.install_from(directory)
    finally:
        shutil.rmtree(directory, ignore_errors=True)
