"""MCP store tests: installed listing, registry search/cache, and install.

A fake httpx client stands in for the live registry so caching, staleness on
a failed fetch, and the npm/PyPI package translation can be exercised without
a network call.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from marvi_gateway import mcp_store
from marvi_gateway.mcp_bridge import McpBridge, load_server_config


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self) -> dict:
        return self._payload


class FakeHttp:
    """Serves one payload per cursor value; page 1 has cursor None."""

    def __init__(self, by_cursor: dict[str | None, dict], fail: bool = False) -> None:
        self.by_cursor = by_cursor
        self.fail = fail
        self.calls: list[dict] = []

    def get(self, url, params=None):
        self.calls.append(dict(params or {}))
        if self.fail:
            raise RuntimeError("registry unreachable")
        cursor = (params or {}).get("cursor")
        return FakeResponse(self.by_cursor[cursor])

    def close(self) -> None:
        pass


def entry(name, title, description, packages=None, remote=False):
    """One registry row in the shape the live API actually returns.

    Every entry is wrapped -- `{"server": {...}, "_meta": {...}}` -- and these
    fixtures used to be written flat, from what the parser assumed rather than
    from a response. So the parser read the wrapper, every field resolved to
    "", and twenty-six passing tests still shipped a store that rendered a
    page of blank rows with an Install button on each. Captured from
    `registry.modelcontextprotocol.io/v0/servers` on 2026-08-28.
    """
    server = {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": name,
        "title": title,
        "description": description,
        "version": "1.0.0",
    }
    if packages:
        server["packages"] = packages
    if remote:
        server["remotes"] = [{"type": "streamable-http", "url": f"https://{name}/mcp"}]
    return {
        "server": server,
        "_meta": {
            "io.modelcontextprotocol.registry/official": {
                "status": "active",
                "isLatest": True,
            }
        },
    }


NPM = [{"registryType": "npm", "identifier": "@example/notion-mcp", "version": "1.2.0"}]

PAGE_1 = {
    "servers": [
        entry("com.example/notion", "Notion", "Read and write Notion pages", packages=NPM)
    ],
    "metadata": {"nextCursor": "cursor-2", "count": 1},
}
PAGE_2 = {
    "servers": [
        entry("com.example/second", "Second", "Another one", packages=NPM),
        # Hosted, with nothing to launch. Marvi's bridge runs a command, so
        # this must not reach the page offering an Install button.
        entry("com.example/hosted", "Hosted", "A remote endpoint", remote=True),
    ],
    "metadata": {"count": 2},
}


# -- installed listing --------------------------------------------------------


def test_installed_servers_reports_tool_counts_and_errors() -> None:
    def tool(name):
        return SimpleNamespace(
            name=name, description="", annotations=SimpleNamespace(readOnlyHint=True), inputSchema=None
        )

    class _Listing:
        def __init__(self, tools):
            self.tools = tools

    class FakeSession:
        async def list_tools(self):
            return _Listing([tool("a"), tool("b")])

    async def factory(spec):
        if spec["name"] == "broken":
            raise RuntimeError("dead")
        return FakeSession()

    bridge = McpBridge(servers=[{"name": "docs"}, {"name": "broken"}], session_factory=factory)
    rows = {row["id"]: row for row in mcp_store.installed_servers(bridge)}

    assert rows["docs"] == {"id": "docs", "name": "docs", "status": "connected", "tools": 2, "source": "installed"}
    assert rows["broken"]["status"] == "error"
    assert rows["broken"]["tools"] == 0


# -- registry search and caching ---------------------------------------------


def test_registry_search_returns_normalised_rows_and_caches_them(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    http = FakeHttp({None: PAGE_1})

    result = mcp_store.registry_search("notion", 1, http=http)

    assert result["stale"] is False
    assert result["servers"] == [
        {
            "qualified_name": "com.example/notion",
            "name": "Notion",
            "description": "Read and write Notion pages",
            "author": "com.example",
            "source": "registry",
            "installable": True,
        }
    ]
    assert result["total_pages"] == 1
    # A search is one request. The `search` parameter applies to the first
    # response only -- follow the cursor and the whole catalogue comes back --
    # so walking one turned a search for "github" into a page of servers
    # beginning "ac.".
    assert len(http.calls) == 1
    assert http.calls[0]["search"] == "notion"

    # Served from the cache on the next call; no second network call.
    again = mcp_store.registry_search("notion", 1, http=FakeHttp({None: PAGE_1}, fail=True))
    assert again == result


def test_a_failed_live_fetch_falls_back_to_cache_and_is_marked_stale(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    mcp_store.registry_search("notion", 1, http=FakeHttp({None: PAGE_1}))

    # `refresh=True` forces past the fresh-cache shortcut, the same as a user
    # pulling to refresh; the live attempt then fails and falls back.
    result = mcp_store.registry_search("notion", 1, http=FakeHttp({}, fail=True), refresh=True)

    assert result["stale"] is True
    assert result["servers"][0]["qualified_name"] == "com.example/notion"


def test_a_failed_fetch_with_nothing_cached_returns_an_empty_stale_page(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    result = mcp_store.registry_search("nothing-cached-yet", 1, http=FakeHttp({}, fail=True))
    assert result == {"servers": [], "total_pages": 1, "stale": True}


def test_browsing_walks_the_cursor_and_drops_what_cannot_be_launched(
    tmp_path, monkeypatch
) -> None:
    """Browsing has no search term to send, so it walks -- and what it collects
    is filtered to servers the stdio bridge can actually start."""
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    http = FakeHttp({None: PAGE_1, "cursor-2": PAGE_2})

    result = mcp_store.registry_search("", 1, http=http)

    assert [row["qualified_name"] for row in result["servers"]] == [
        "com.example/notion",
        "com.example/second",
    ]
    assert len(http.calls) == 2
    assert http.calls[1]["cursor"] == "cursor-2"
    assert "search" not in http.calls[0]


def test_the_same_server_published_many_times_appears_once(tmp_path, monkeypatch) -> None:
    """The registry publishes every *version* as its own row: 1,200 rows
    carried 298 distinct servers and one name accounted for 302 of them. A
    page of twenty was twenty copies of one server, each with an Install
    button."""
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    repeated = {
        "servers": [
            entry("com.example/notion", "Notion", "v1", packages=NPM),
            entry("com.example/notion", "Notion", "v2", packages=NPM),
            entry("com.example/notion", "Notion", "v3", packages=NPM),
        ],
        "metadata": {"count": 3},
    }

    result = mcp_store.registry_search("", 1, http=FakeHttp({None: repeated}))

    assert len(result["servers"]) == 1
    # Newest wins: the registry returns a name's versions oldest-first.
    assert result["servers"][0]["description"] == "v3"


# -- install -------------------------------------------------------------


def test_install_resolves_an_npm_package_and_persists_the_server_spec(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    monkeypatch.delenv("MARVI_MCP_SERVERS", raising=False)
    monkeypatch.delenv("MARVI_MCP_CONFIG", raising=False)
    http = FakeHttp({None: PAGE_1})

    spec = mcp_store.install("com.example/notion", {"NOTION_TOKEN": "x"}, http=http)

    assert spec == {
        "name": "notion",
        "command": "npx",
        "args": ["-y", "@example/notion-mcp@1.2.0"],
        "env": {"NOTION_TOKEN": "x"},
    }
    assert load_server_config() == [spec]


def test_install_refuses_an_unknown_qualified_name(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    with pytest.raises(mcp_store.McpStoreError, match="not found"):
        mcp_store.install("nope/nothing", {}, http=FakeHttp({None: PAGE_1}))


def test_install_refuses_a_package_type_the_bridge_cannot_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    docker_only = {
        "servers": [
            {
                "name": "com.example/docker-only",
                "title": "Docker Only",
                "description": "",
                "packages": [{"registryType": "oci", "identifier": "example/image"}],
            }
        ],
        "metadata": {"count": 1},
    }
    with pytest.raises(mcp_store.McpStoreError, match="container runtime"):
        mcp_store.install("com.example/docker-only", {}, http=FakeHttp({None: docker_only}))
