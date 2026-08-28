"""The MCP store: installed servers, and the public registry to install from.

`mcp_bridge.py` is the client — connect to whatever is configured, expose its
tools. Nothing let a user browse what else exists or add a server without
hand-editing JSON and restarting Gateway. This is that surface, over the
official Model Context Protocol registry (`registry.modelcontextprotocol.io`):
a public, unauthenticated, community-run index rather than one company's
catalog behind an API key — the same "no reusable project secret" and "no
independently administered integration platform" constraints AGENTS.md
already holds Composio to apply here too, and openhuman's Smithery-backed
registry would not (a project key to embed, a vendor account to create).

Cached on disk the way the skill store caches its catalogue
(`setup/store.py`), because a registry search is a real HTTP round trip and
nothing waiting on this Gateway's response should be able to hang behind a
slow or unreachable upstream.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .logs import get_logger
from .mcp_bridge import McpBridge

log = get_logger("setup")

REGISTRY_API = "https://registry.modelcontextprotocol.io"
REQUEST_TIMEOUT = 5.0
#: Same reasoning as setup/store.py's CACHE_HOURS: a registry of published MCP
#: servers changes on the timescale of days, and the second search for the
#: same query should not pay for a network round trip.
CACHE_HOURS = 12.0
PAGE_SIZE = 20
#: Registry pagination is cursor-based, not page-numbered — there is no
#: single request for "page 4". Walking from page 1 is fine for the shallow
#: browsing a local desktop store does; this caps the walk so a stray
#: page=9000 cannot turn into hundreds of sequential requests.
MAX_WALK_PAGES = 20


class McpStoreError(Exception):
    """A registry entry cannot be installed as asked."""


def _pick(value: Any, *names: str) -> Any:
    if not isinstance(value, dict):
        return None
    for name in names:
        found = value.get(name)
        if found not in (None, ""):
            return found
    return None


def installed_servers(bridge: McpBridge) -> list[dict[str, Any]]:
    """Every configured server and its live status, for `GET /mcp/servers`."""
    rows = []
    for entry in bridge.list_tools():
        rows.append(
            {
                "id": entry["server"],
                "name": entry["server"],
                "status": "error" if entry["error"] else "connected",
                "tools": len(entry["tools"]),
                "source": "installed",
            }
        )
    return rows


def cache_path() -> Path:
    from .paths import root

    return root() / "state" / "mcp-registry-cache.json"


def _cache_key(query: str, page: int) -> str:
    return f"{query.strip().lower()}|{page}"


def _cached(query: str, page: int) -> dict[str, Any] | None:
    try:
        saved = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = saved.get(_cache_key(query, page)) if isinstance(saved, dict) else None
    return entry if isinstance(entry, dict) else None


def _save(query: str, page: int, entry: dict[str, Any]) -> None:
    path = cache_path()
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            existing = {}
    except (OSError, ValueError):
        existing = {}
    existing[_cache_key(query, page)] = entry
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing), encoding="utf-8")
    except OSError as exc:  # pragma: no cover - depends on the filesystem
        log.warning("could not cache the MCP registry page: %s", exc)


def _fetch_page(query: str, page: int, http: Any = None) -> tuple[list[dict[str, Any]], bool]:
    """One page of the live registry, walking cursors from page 1.

    The API is cursor-paginated rather than page-numbered, and there is no
    cheaper way to reach page N than to have already walked pages 1..N-1.
    """
    import httpx

    client = http or httpx.Client(timeout=REQUEST_TIMEOUT)
    try:
        cursor = None
        rows: list[dict[str, Any]] = []
        has_more = False
        for _ in range(min(max(1, page), MAX_WALK_PAGES)):
            params: dict[str, Any] = {"limit": PAGE_SIZE}
            if query:
                params["search"] = query
            if cursor:
                params["cursor"] = cursor
            response = client.get(f"{REGISTRY_API}/v0/servers", params=params)
            response.raise_for_status()
            body = response.json()
            rows = [row for row in (body.get("servers") or []) if isinstance(row, dict)]
            cursor = (body.get("metadata") or {}).get("nextCursor")
            has_more = bool(cursor)
        return rows, has_more
    finally:
        if http is None:
            client.close()


def _row(entry: dict[str, Any]) -> dict[str, Any]:
    qualified = str(_pick(entry, "name") or "")
    meta = entry.get("_meta")
    publisher = (
        meta.get("io.modelcontextprotocol.registry/publisher-provided")
        if isinstance(meta, dict)
        else None
    )
    author = ""
    if isinstance(publisher, dict):
        author = str(publisher.get("author") or publisher.get("name") or "")
    if not author and "/" in qualified:
        author = qualified.split("/", 1)[0]
    return {
        "qualified_name": qualified,
        "name": str(_pick(entry, "title") or qualified),
        "description": str(_pick(entry, "description") or "")[:300],
        "author": author,
        "source": "registry",
    }


def registry_search(
    query: str, page: int = 1, http: Any = None, *, refresh: bool = False
) -> dict[str, Any]:
    """Search results plus a staleness marker, so a hung upstream never blocks.

    Served from cache first when one is fresh. A live fetch that fails —
    timeout, DNS, a 5xx — falls back to whatever is cached rather than
    turning a slow registry into a broken page, and marks the result `stale`
    rather than pretending it is current.
    """
    page = max(1, page)
    # Read unconditionally, even under `refresh=True` -- a forced refresh
    # still wants this as the fallback if the live attempt below fails, and
    # nulling it out for a "no fallback" refresh would turn "try again" into
    # "throw away what I already had if the network hiccups".
    on_disk = _cached(query, page)
    now = time.time()
    if not refresh and on_disk is not None and now - float(on_disk.get("at") or 0) <= CACHE_HOURS * 3600:
        return {"servers": on_disk["rows"], "total_pages": on_disk["total_pages"], "stale": False}
    try:
        rows, has_more = _fetch_page(query, page, http)
        entry = {
            "at": now,
            "rows": [_row(row) for row in rows],
            # The registry never returns a total count. "At least this many
            # pages, one more if the cursor says so" is the honest thing to
            # report rather than inventing a total the API does not give.
            "total_pages": page + (1 if has_more else 0),
        }
        _save(query, page, entry)
        return {"servers": entry["rows"], "total_pages": entry["total_pages"], "stale": False}
    except Exception as exc:
        log.warning("MCP registry search failed: %s", exc)
        if on_disk is not None:
            return {"servers": on_disk["rows"], "total_pages": on_disk["total_pages"], "stale": True}
        return {"servers": [], "total_pages": page, "stale": True}


def _install_spec(name: str, package: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    """Turn one registry package entry into an `mcp_bridge` stdio server spec.

    The registry lists several ways to run a server (npm, PyPI, an OCI image,
    a remote URL); this picks the one Marvi's stdio-only bridge can act on
    without asking the user to have Docker or another container runtime
    installed, in the same no-Docker-requirement spirit as ADR-003.
    """
    registry_type = str(
        _pick(package, "registryType", "registry_type", "registry_name") or ""
    ).lower()
    identifier = str(_pick(package, "identifier", "name") or "")
    version = str(_pick(package, "version") or "").strip()
    if not identifier:
        raise McpStoreError("that registry entry has no package identifier to install")
    if "npm" in registry_type or "node" in registry_type:
        target = f"{identifier}@{version}" if version and version != "latest" else identifier
        command, args = "npx", ["-y", target]
    elif "pypi" in registry_type or "python" in registry_type:
        target = f"{identifier}=={version}" if version and version != "latest" else identifier
        command, args = "uvx", [target]
    else:
        raise McpStoreError(
            f"{identifier}: {registry_type or 'this package type'} needs a container "
            "runtime Marvi's MCP bridge does not manage; install a stdio (npm or "
            "PyPI) package instead"
        )
    return {"name": name, "command": command, "args": args, "env": env}


def install(qualified_name: str, env: dict[str, str], http: Any = None) -> dict[str, Any]:
    """Resolve a registry entry to a runnable server, and install it.

    Looked up with an exact `search` against the qualified name rather than a
    dedicated by-name endpoint, to reuse the same cached, timeout-guarded path
    the browsing routes use instead of a second lookup with its own failure
    modes. Raises `McpStoreError` for anything the caller did wrong (unknown
    name, no runnable package) so the route can answer 422 rather than 502.

    Installing goes through `setup/mcp.py`'s existing prepare-then-add flow
    rather than writing a config file directly, for two reasons: it is
    already the one writer of `paths.mcp_config()`, in the format Claude
    Desktop, Cursor and VS Code share, and a second writer with its own
    schema would silently corrupt whatever it wrote; and its `prepare` step
    is what resolves the runner on PATH and binds the exact argv that `add`
    then commits — the "Install" click here is the approval, but the
    resolved command still goes through the one path that checks it before
    anything is written.
    """
    import httpx

    from .setup import mcp as mcp_setup

    client = http or httpx.Client(timeout=REQUEST_TIMEOUT)
    try:
        response = client.get(
            f"{REGISTRY_API}/v0/servers", params={"search": qualified_name, "limit": 10}
        )
        response.raise_for_status()
        body = response.json()
    except McpStoreError:
        raise
    except Exception as exc:
        raise McpStoreError(f"could not reach the MCP registry: {exc}") from exc
    finally:
        if http is None:
            client.close()

    entry = next(
        (row for row in (body.get("servers") or []) if _pick(row, "name") == qualified_name),
        None,
    )
    if entry is None:
        raise McpStoreError(f"{qualified_name} was not found in the registry")
    packages = entry.get("packages")
    if not isinstance(packages, list) or not packages:
        raise McpStoreError(f"{qualified_name} has no installable package listed")
    short_name = qualified_name.rsplit("/", 1)[-1]
    spec = _install_spec(short_name, packages[0], env)

    prepared = mcp_setup.prepare(spec["name"], spec["command"], spec["args"], spec["env"])
    result = mcp_setup.add(prepared["token"])
    if not result.get("ok"):
        raise McpStoreError(str(result.get("detail") or "could not install"))
    log.info(
        "MCP server installed",
        extra={"marvi_server": spec["name"], "marvi_qualified_name": qualified_name},
    )
    return spec
