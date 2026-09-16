"""Finding what was said in an old conversation."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.chat import ChatStore, register_chat_search_tool
from marvi_gateway.tools import ToolRegistry


def _store(tmp_path) -> ChatStore:
    store = ChatStore(tmp_path / "chat.db")
    trip = store.create_thread("Trip planning")["id"]
    store.append("user", "Book the hotel in Alexandria for October", thread_id=trip)
    store.append("assistant", "Done -- the Alexandria hotel is held until Friday.", thread_id=trip)
    other = store.create_thread("Groceries")["id"]
    store.append("user", "Add 100% orange juice to the list", thread_id=other)
    store.update_thread(trip, archived=True)
    return store


def test_it_finds_messages_across_threads_newest_first(tmp_path) -> None:
    found = _store(tmp_path).search("alexandria")
    assert [row["role"] for row in found] == ["assistant", "user"]
    assert found[0]["title"] == "Trip planning" and found[0]["archived"] is True
    assert "Alexandria hotel" in found[0]["snippet"]


def test_like_wildcards_are_literal(tmp_path) -> None:
    store = _store(tmp_path)
    assert len(store.search("100%")) == 1
    # A bare percent sign is the one literal percent, not "everything".
    assert [row["title"] for row in store.search("%")] == ["Groceries"]
    assert store.search("_") == []
    assert store.search("   ") == []


def test_the_tool_wraps_old_replies_as_data(tmp_path) -> None:
    registry = ToolRegistry()
    register_chat_search_tool(registry, _store(tmp_path))
    spec = registry.get("chat_search")
    result = registry.execute(spec, registry.validate(spec, {"query": "hotel"}))
    assert result["count"] == 2 and "Alexandria" in str(result["results"])
    assert registry.execute(spec, {"query": "nowhere"})["results"] == []


@pytest.mark.asyncio
async def test_the_endpoint_answers(tmp_path, monkeypatch) -> None:
    from marvi_gateway.app import create_app

    monkeypatch.setenv("MARVI_CHAT_DB", str(tmp_path / "chat.db"))
    _store(tmp_path)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/chat/search", params={"q": "orange"})
    assert response.status_code == 200
    assert response.json()["results"][0]["title"] == "Groceries"


def test_a_thread_exports_as_markdown(tmp_path) -> None:
    """S9: the conversation as it was read, with its sources kept."""
    store = _store(tmp_path)
    trip = next(t["id"] for t in store.threads(archived=True) if t["title"] == "Trip planning")

    exported = store.export_markdown(trip)

    assert exported["title"] == "Trip planning"
    body = exported["markdown"]
    assert body.startswith("# Trip planning")
    assert "## You ·" in body and "## Marvi ·" in body
    assert "Book the hotel in Alexandria" in body
    assert body.endswith("\n")


def test_exporting_a_thread_that_is_not_there_is_an_error(tmp_path) -> None:
    import pytest as _pytest

    with _pytest.raises(KeyError):
        _store(tmp_path).export_markdown("no-such-thread")
