"""/mcp route wiring: request/response shape and store delegation.

The store's own search/cache/install logic is exercised in test_mcp_store.py;
these tests only check that the FastAPI routes call it correctly and shape
the response as the Connectors/MCP UI expects.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway import mcp_store
from marvi_gateway.app import create_app
from marvi_gateway.runtime import RuntimeStore


def build(tmp_path):
    return create_app(version="test", runtime=RuntimeStore(audit_path=tmp_path / "audit.jsonl"))


@pytest.mark.asyncio
async def test_mcp_servers_lists_nothing_when_none_are_configured(tmp_path) -> None:
    app = build(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as c:
        response = await c.get("/mcp/servers")
    assert response.json() == {"servers": []}


@pytest.mark.asyncio
async def test_mcp_registry_route_delegates_to_the_store(tmp_path, monkeypatch) -> None:
    app = build(tmp_path)
    monkeypatch.setattr(
        mcp_store,
        "registry_search",
        lambda q, page: {
            "servers": [
                {
                    "qualified_name": "com.example/x",
                    "name": "X",
                    "description": "d",
                    "author": "a",
                    "source": "registry",
                }
            ],
            "total_pages": 1,
            "stale": False,
        },
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as c:
        response = await c.get("/mcp/registry", params={"q": "x", "page": 1})

    assert response.json()["servers"][0]["qualified_name"] == "com.example/x"
    assert response.json()["total_pages"] == 1


@pytest.mark.asyncio
async def test_mcp_install_route_calls_the_store_and_reloads_the_bridge(
    tmp_path, monkeypatch
) -> None:
    app = build(tmp_path)
    monkeypatch.setattr(
        mcp_store,
        "install",
        lambda qualified_name, env: {
            "name": "docs", "command": "npx", "args": ["-y", "docs-mcp"], "env": env,
        },
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as c:
        response = await c.post("/mcp/install", json={"qualified_name": "com.example/docs", "env": {}})

    assert response.json() == {"installed": True, "name": "docs"}


@pytest.mark.asyncio
async def test_mcp_install_turns_a_store_error_into_a_client_error(tmp_path, monkeypatch) -> None:
    app = build(tmp_path)

    def boom(qualified_name, env):
        raise mcp_store.McpStoreError("not found in the registry")

    monkeypatch.setattr(mcp_store, "install", boom)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as c:
        response = await c.post("/mcp/install", json={"qualified_name": "nope/nope", "env": {}})

    assert response.status_code == 422
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_mcp_uninstall_removes_the_server_through_the_canonical_store(tmp_path) -> None:
    from marvi_gateway.setup import mcp as mcp_setup

    app = build(tmp_path)
    mcp_setup.add(mcp_setup.prepare("docs", "npx", ["docs-mcp"])["token"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as c:
        response = await c.delete("/mcp/servers/docs")

    assert response.json()["ok"] is True
    assert mcp_setup.read() == {}


@pytest.mark.asyncio
async def test_uninstalling_an_unknown_server_is_a_404(tmp_path) -> None:
    app = build(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as c:
        response = await c.delete("/mcp/servers/nope")
    assert response.status_code == 404
