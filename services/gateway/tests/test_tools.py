from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.app import create_app
from marvi_gateway.runtime import (
    CONFIRMATION_TTL_SECONDS,
    TERMINAL_NOTIFICATION_TTL_SECONDS,
    RuntimeStore,
)
from marvi_gateway.tools import ToolRegistry, ToolSpec


@pytest.fixture
def registry() -> ToolRegistry:
    calls: list[dict] = []

    def set_light(**args):
        calls.append(args)
        return {"ok": True, "brightness": args["brightness"]}

    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            name="room_set_light",
            description="Set the room light brightness.",
            arguments={"brightness": int},
            sensitive=True,
            handler=set_light,
        )
    )
    tools.register(
        ToolSpec(
            name="room_state",
            description="Read room state.",
            arguments={},
            sensitive=False,
            handler=lambda **_: {"present": True},
        )
    )
    tools.calls = calls  # type: ignore[attr-defined]
    return tools


@pytest.fixture
def client_factory(registry, tmp_path):
    def build(yolo: bool = False):
        runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
        runtime.set_yolo(yolo)
        app = create_app(version="0.1.0-test", runtime=runtime, tools=registry)
        return AsyncClient(
            transport=ASGITransport(app=app), base_url="http://marvi.local"
        ), runtime

    return build


@pytest.mark.asyncio
async def test_sensitive_tool_requests_confirmation_instead_of_executing(
    client_factory, registry
) -> None:
    client, runtime = client_factory()
    async with client:
        response = await client.post(
            "/tools/room_set_light", json={"arguments": {"brightness": 40}}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmation_required"
    assert body["token"]
    assert registry.calls == []
    assert runtime.assistant.confirmation is not None
    assert runtime.assistant.confirmation.token == body["token"]


@pytest.mark.asyncio
async def test_approval_executes_once_and_replay_is_rejected(
    client_factory, registry
) -> None:
    client, _ = client_factory()
    async with client:
        requested = await client.post(
            "/tools/room_set_light", json={"arguments": {"brightness": 40}}
        )
        token = requested.json()["token"]
        first = await client.post(
            f"/confirmations/{token}",
            json={"decision": "approve", "arguments": {"brightness": 40}},
        )
        replay = await client.post(
            f"/confirmations/{token}",
            json={"decision": "approve", "arguments": {"brightness": 40}},
        )

    assert first.status_code == 200
    assert first.json()["status"] == "executed"
    assert replay.status_code == 404
    assert registry.calls == [{"brightness": 40}]


@pytest.mark.asyncio
async def test_mutated_arguments_are_rejected_and_burn_the_token(
    client_factory, registry
) -> None:
    client, _ = client_factory()
    async with client:
        requested = await client.post(
            "/tools/room_set_light", json={"arguments": {"brightness": 40}}
        )
        token = requested.json()["token"]
        mutated = await client.post(
            f"/confirmations/{token}",
            json={"decision": "approve", "arguments": {"brightness": 100}},
        )
        retry_with_original = await client.post(
            f"/confirmations/{token}",
            json={"decision": "approve", "arguments": {"brightness": 40}},
        )

    assert mutated.status_code == 409
    assert retry_with_original.status_code == 404
    assert registry.calls == []


@pytest.mark.asyncio
async def test_expired_token_is_rejected(client_factory, registry) -> None:
    client, runtime = client_factory()
    async with client:
        requested = await client.post(
            "/tools/room_set_light", json={"arguments": {"brightness": 40}}
        )
        token = requested.json()["token"]
        runtime.expire_confirmations(now=runtime.pending_issued_at(token) + 10_000)
        expired = await client.post(
            f"/confirmations/{token}",
            json={"decision": "approve", "arguments": {"brightness": 40}},
        )

    assert expired.status_code == 404
    assert registry.calls == []


@pytest.mark.asyncio
async def test_runtime_poll_expires_and_then_collapses_confirmation(
    client_factory,
) -> None:
    client, runtime = client_factory()
    async with client:
        requested = await client.post(
            "/tools/room_set_light", json={"arguments": {"brightness": 40}}
        )
        token = requested.json()["token"]
        issued = runtime.pending_issued_at(token)
        runtime.expire_transients(now=issued + CONFIRMATION_TTL_SECONDS + 1)
        assert runtime.assistant.phase == "notification"
        assert runtime.assistant.confirmation is None

        runtime.expire_transients(
            now=issued
            + CONFIRMATION_TTL_SECONDS
            + TERMINAL_NOTIFICATION_TTL_SECONDS
            + 2
        )

    assert runtime.assistant.phase == "ready"
    assert runtime.assistant.confirmation is None


@pytest.mark.asyncio
async def test_denial_never_executes(client_factory, registry) -> None:
    client, _ = client_factory()
    async with client:
        requested = await client.post(
            "/tools/room_set_light", json={"arguments": {"brightness": 40}}
        )
        token = requested.json()["token"]
        denied = await client.post(
            f"/confirmations/{token}",
            json={"decision": "deny", "arguments": {"brightness": 40}},
        )

    assert denied.status_code == 200
    assert denied.json()["status"] == "denied"
    assert registry.calls == []


@pytest.mark.asyncio
async def test_yolo_executes_sensitive_tools_without_confirmation(
    client_factory, registry
) -> None:
    client, runtime = client_factory(yolo=True)
    async with client:
        response = await client.post(
            "/tools/room_set_light", json={"arguments": {"brightness": 40}}
        )

    assert response.json()["status"] == "executed"
    assert registry.calls == [{"brightness": 40}]
    assert runtime.assistant.confirmation is None
    assert runtime.assistant.yolo is True


@pytest.mark.asyncio
async def test_enabling_yolo_dismisses_existing_confirmation(
    client_factory, registry
) -> None:
    client, runtime = client_factory()
    async with client:
        requested = await client.post(
            "/tools/room_set_light", json={"arguments": {"brightness": 40}}
        )
        token = requested.json()["token"]
        changed = await client.put("/runtime/mode", json={"yolo": True})
        replay = await client.post(
            f"/confirmations/{token}",
            json={"decision": "approve", "arguments": {"brightness": 40}},
        )

    assert changed.json()["assistant"]["yolo"] is True
    assert changed.json()["assistant"]["confirmation"] is None
    assert replay.status_code == 404
    assert registry.calls == []
    assert runtime.assistant.confirmation is None


@pytest.mark.asyncio
async def test_insensitive_tool_never_asks_for_confirmation(
    client_factory, registry
) -> None:
    client, _ = client_factory()
    async with client:
        response = await client.post("/tools/room_state", json={"arguments": {}})

    assert response.json()["status"] == "executed"
    assert response.json()["result"] == {"present": True}


@pytest.mark.asyncio
async def test_unknown_tool_and_bad_arguments_are_refused(client_factory) -> None:
    client, _ = client_factory()
    async with client:
        unknown = await client.post("/tools/drop_database", json={"arguments": {}})
        missing = await client.post("/tools/room_set_light", json={"arguments": {}})
        extra = await client.post(
            "/tools/room_set_light",
            json={"arguments": {"brightness": 40, "shell": "rm -rf"}},
        )

    assert unknown.status_code == 404
    assert missing.status_code == 422
    assert extra.status_code == 422


@pytest.mark.asyncio
async def test_yolo_execution_is_still_audited(client_factory, tmp_path) -> None:
    client, runtime = client_factory(yolo=True)
    async with client:
        await client.post(
            "/tools/room_set_light", json={"arguments": {"brightness": 40}}
        )
        audit = await client.get("/audit")

    records = [json.loads(line) for line in runtime.audit_path.read_text().splitlines()]
    assert [record["event"] for record in records] == ["requested", "executed"]
    assert records[0]["mode"] == "yolo"
    assert records[0]["arguments"] == {"brightness": 40}
    assert audit.json()["events"][0]["tool"] == "room_set_light"


@pytest.mark.asyncio
async def test_audit_records_the_full_confirmation_lifecycle(
    client_factory, registry
) -> None:
    client, runtime = client_factory()
    async with client:
        requested = await client.post(
            "/tools/room_set_light", json={"arguments": {"brightness": 40}}
        )
        token = requested.json()["token"]
        await client.post(
            f"/confirmations/{token}",
            json={"decision": "approve", "arguments": {"brightness": 40}},
        )

    records = [json.loads(line) for line in runtime.audit_path.read_text().splitlines()]
    assert [record["event"] for record in records] == [
        "requested",
        "confirmation_required",
        "approved",
        "executed",
    ]
    assert all(record["mode"] == "confirm" for record in records)


@pytest.mark.asyncio
async def test_failing_tool_is_audited_and_does_not_crash_the_gateway(
    client_factory, registry
) -> None:
    registry.register(
        ToolSpec(
            name="room_health",
            description="Sidecar health.",
            arguments={},
            sensitive=False,
            handler=lambda **_: (_ for _ in ()).throw(RuntimeError("sidecar is down")),
        )
    )
    client, runtime = client_factory()
    async with client:
        response = await client.post("/tools/room_health", json={"arguments": {}})
        still_alive = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "sidecar is down" in response.json()["error"]
    assert still_alive.status_code == 200

    records = [json.loads(line) for line in runtime.audit_path.read_text().splitlines()]
    assert records[-1]["event"] == "failed"
