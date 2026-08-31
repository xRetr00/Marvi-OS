"""/connectors route tests: Marvi Connectors presented over ComposioAccounts.

A small fake SDK stands in for Composio, in the same shape
test_account_platform.py's LifecycleSdk uses, kept local so this file does
not depend on cross-file imports or collection order.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.accounts import AccountStateStore, ComposioAccounts
from marvi_gateway.app import create_app
from marvi_gateway.runtime import RuntimeStore


class Model:
    def __init__(self, **values):
        self.__dict__.update(values)


class ConnectorSdk:
    """One active gmail connection; every other native toolkit unconnected."""

    def __init__(self) -> None:
        self.account_items = [
            Model(id="ca_gmail", toolkit=Model(slug="gmail"), status="ACTIVE", alias="")
        ]
        self.connected_accounts = Model(
            list=lambda **_kwargs: Model(items=self.account_items),
            delete=self._delete,
        )
        self.toolkits = Model()
        # The handoff goes through `client.link.create` against an auth config
        # id. `toolkits.authorize` was retired upstream mid-development and
        # answered every connect with "Use POST /api/v3/connected_accounts/link
        # instead" -- which reached the user as "Invalid authorization URL".
        # Mirrors the real shape: `auth_configs` on the SDK facade, `link` on
        # the generated client one layer below it.
        self.auth_configs = Model(
            list=lambda toolkit_slug=None, **_kw: Model(
                items=[{"id": f"ac_{toolkit_slug}", "type": "default"}]
            ),
            create=lambda **kw: {"auth_config": {"id": "ac_made"}},
        )
        self.client = Model(
            link=Model(
                create=lambda auth_config_id, user_id, **_kw: {
                    "connected_account_id": "ca_new",
                    "redirect_url": f"https://connect.composio.dev/link/lk_{auth_config_id}",
                }
            ),
        )
        self.tools = Model(
            get_raw_composio_tools=lambda **_kwargs: [],
            get_raw_composio_tool_by_slug=lambda slug: Model(
                slug=slug, name=slug, description="", toolkit=Model(slug="gmail"),
                input_parameters={"type": "object"}, version="1", human_description=None,
            ),
            execute=lambda **kwargs: {
                "successful": True,
                "data": {"messages": [{"id": "m1", "subject": "Hi", "body": "hello", "date": "1"}]},
            },
        )

    def _delete(self, connection_id, **_kwargs):
        self.account_items = [row for row in self.account_items if row.id != connection_id]
        return {"id": connection_id}


def build(tmp_path):
    sdk = ConnectorSdk()
    state = AccountStateStore(tmp_path / "accounts.sqlite3")
    accounts = ComposioAccounts(key="k", client=sdk, state=state)
    app = create_app(
        version="test",
        runtime=RuntimeStore(audit_path=tmp_path / "audit.jsonl"),
        account_service=accounts,
    )
    return app, sdk


@pytest.mark.asyncio
async def test_connectors_list_separates_connected_from_never_connected(tmp_path) -> None:
    app, _ = build(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as c:
        response = await c.get("/connectors")

    body = response.json()
    assert body["available"] is True
    rows = {row["slug"]: row for row in body["connectors"]}
    assert rows["gmail"]["status"] == "connected"
    assert rows["gmail"]["connection_id"] == "ca_gmail"
    assert rows["gmail"]["places"]["tool"] is True
    assert rows["gmail"]["places"]["memory"] is True
    # No automatic personalization surface exists; reported honestly.
    assert rows["gmail"]["places"]["profile"] is False
    # Supported, never connected. Not "preview" -- that rendered amber beside
    # a real expired-auth amber and made six untouched services look special.
    assert rows["notion"]["status"] == "disconnected"
    assert rows["notion"]["connection_id"] == ""
    assert rows["notion"]["places"] == {
        "tool": False, "memory": False, "profile": False, "triggers": False,
    }


@pytest.mark.asyncio
async def test_connector_detail_is_the_cheap_poll_target(tmp_path) -> None:
    app, _ = build(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as c:
        gmail = await c.get("/connectors/gmail")
        unknown = await c.get("/connectors/spotify")

    assert gmail.json()["status"] == "connected"
    assert gmail.json()["connections"] == 1
    assert unknown.json()["status"] == "disconnected"


@pytest.mark.asyncio
async def test_connector_connect_returns_a_link(tmp_path) -> None:
    app, _ = build(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as c:
        response = await c.post("/connectors/notion/connect")

    assert response.json()["connect_url"].startswith("https://connect.composio.dev/")
    assert response.json()["connection_id"] == "ca_new"


@pytest.mark.asyncio
async def test_connector_scope_updates_the_local_ceiling(tmp_path) -> None:
    app, _ = build(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as c:
        response = await c.post("/connectors/gmail/scope", json={"scope": "write"})

    body = response.json()
    assert body["slug"] == "gmail"
    assert body["scope"] == "write"
    assert body["sync_enabled"] is True


@pytest.mark.asyncio
async def test_disconnecting_a_connector_retracts_what_it_ingested(tmp_path) -> None:
    app, sdk = build(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as c:
        await c.post("/accounts/sync", json={})
        before = await c.get("/connectors/gmail")
        deleted = await c.delete("/connectors/connections/ca_gmail")
        after = await c.get("/connectors/gmail")

    assert before.json()["memory_items"] == 1
    assert deleted.json()["deleted"] is True
    assert deleted.json()["retracted"] == {
        "toolkit": "gmail", "connection_id": "ca_gmail", "sources": 1, "removed": 1,
    }
    assert after.json()["status"] == "disconnected"  # the fake SDK no longer lists it
    assert after.json()["memory_items"] == 0
    assert sdk.account_items == []


def test_a_connection_being_set_up_is_not_reported_as_expired() -> None:
    """Composio reports INITIALIZING during the handshake, and every status
    that was not live fell through to "expired". Connecting a calendar showed
    "Authorization expired. Reconnect to keep using this connector." over a
    connection two seconds from working -- with a Reconnect button under it --
    and then it turned green on its own.
    """
    from marvi_gateway.accounts import DEAD_STATUSES, LIVE_STATUSES, PENDING_STATUSES

    assert "initializing" in PENDING_STATUSES
    assert not PENDING_STATUSES & DEAD_STATUSES, "a pending connection is not a dead one"
    assert not PENDING_STATUSES & LIVE_STATUSES, "nor is it a live one"
