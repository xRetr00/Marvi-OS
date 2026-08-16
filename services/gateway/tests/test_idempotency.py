"""Duplicate-write protection for external actions.

An email sent twice is not the same as a light set twice. Tools that reach
outside the machine declare themselves external, and the router refuses to run
the same external action twice.
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.app import create_app
from marvi_gateway.runtime import EXTERNAL_WRITE_TTL_SECONDS, RuntimeStore
from marvi_gateway.tools import ToolRegistry, ToolSpec


@pytest.fixture
def gateway(tmp_path):
    sent: list[dict] = []
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="send_email",
            description="Send an email",
            arguments={"to": str, "body": str},
            sensitive=True,
            external=True,
            handler=lambda **args: sent.append(args) or {"id": f"msg-{len(sent)}"},
        )
    )
    registry.register(
        ToolSpec(
            name="room_set_light",
            description="Change the room light",
            arguments={"on": bool},
            sensitive=True,
            handler=lambda **args: {"ok": True},
        )
    )
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    app = create_app(version="0.1.0-test", runtime=runtime, tools=registry)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://marvi.local")
    return client, runtime, sent


async def approve(client, token, arguments):
    return await client.post(
        f"/confirmations/{token}", json={"decision": "approve", "arguments": arguments}
    )


@pytest.mark.asyncio
async def test_the_same_external_write_does_not_send_twice(gateway) -> None:
    client, _, sent = gateway
    args = {"to": "alex@example.com", "body": "hi"}
    async with client:
        first = await client.post("/tools/send_email", json={"arguments": args})
        first_result = await approve(client, first.json()["token"], args)
        # The agent retries the identical call, e.g. after a timeout.
        repeat = await client.post("/tools/send_email", json={"arguments": args})

    assert first_result.json()["status"] == "executed"
    assert repeat.json()["status"] == "executed"
    assert repeat.json()["deduplicated"] is True
    assert repeat.json()["result"] == first_result.json()["result"]
    assert sent == [args]


@pytest.mark.asyncio
async def test_a_duplicate_does_not_ask_the_user_to_confirm_again(gateway) -> None:
    client, runtime, sent = gateway
    args = {"to": "alex@example.com", "body": "hi"}
    async with client:
        first = await client.post("/tools/send_email", json={"arguments": args})
        await approve(client, first.json()["token"], args)
        repeat = await client.post("/tools/send_email", json={"arguments": args})

    # The action already happened; asking again would be a second decision
    # about a thing that is already done.
    assert repeat.json()["status"] != "confirmation_required"
    assert runtime.assistant.confirmation is None
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_different_arguments_are_a_different_action(gateway) -> None:
    client, _, sent = gateway
    one = {"to": "alex@example.com", "body": "hi"}
    two = {"to": "sam@example.com", "body": "hi"}
    async with client:
        first = await client.post("/tools/send_email", json={"arguments": one})
        await approve(client, first.json()["token"], one)
        second = await client.post("/tools/send_email", json={"arguments": two})
        await approve(client, second.json()["token"], two)

    assert sent == [one, two]


@pytest.mark.asyncio
async def test_an_explicit_idempotency_key_overrides_argument_matching(gateway) -> None:
    client, _, sent = gateway
    async with client:
        first = await client.post(
            "/tools/send_email",
            json={"arguments": {"to": "a@x.com", "body": "one"}, "idempotency_key": "thread-7"},
        )
        await approve(client, first.json()["token"], {"to": "a@x.com", "body": "one"})
        # Different text, same logical action.
        repeat = await client.post(
            "/tools/send_email",
            json={"arguments": {"to": "a@x.com", "body": "two"}, "idempotency_key": "thread-7"},
        )

    assert repeat.json()["deduplicated"] is True
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_the_record_expires_so_a_later_deliberate_resend_works(gateway) -> None:
    client, runtime, sent = gateway
    args = {"to": "alex@example.com", "body": "daily report"}
    async with client:
        first = await client.post("/tools/send_email", json={"arguments": args})
        await approve(client, first.json()["token"], args)
        runtime.expire_external_writes(now=runtime.now() + EXTERNAL_WRITE_TTL_SECONDS + 1)
        again = await client.post("/tools/send_email", json={"arguments": args})
        await approve(client, again.json()["token"], args)

    assert len(sent) == 2


@pytest.mark.asyncio
async def test_non_external_tools_are_never_deduplicated(gateway) -> None:
    client, _, _ = gateway
    args = {"on": True}
    async with client:
        first = await client.post("/tools/room_set_light", json={"arguments": args})
        first_done = await approve(client, first.json()["token"], args)
        second = await client.post("/tools/room_set_light", json={"arguments": args})

    # Turning a light on twice is legitimate and must still ask.
    assert first_done.json()["status"] == "executed"
    assert second.json()["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_a_failed_external_write_is_not_recorded_as_done(tmp_path) -> None:
    attempts: list[int] = []

    def flaky(**_args):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("smtp timeout")
        return {"id": "msg-1"}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="send_email",
            description="Send an email",
            arguments={"to": str},
            sensitive=False,
            external=True,
            handler=flaky,
        )
    )
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    app = create_app(version="0.1.0-test", runtime=runtime, tools=registry)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://marvi.local"
    ) as client:
        failed = await client.post("/tools/send_email", json={"arguments": {"to": "a@x.com"}})
        retried = await client.post("/tools/send_email", json={"arguments": {"to": "a@x.com"}})

    assert failed.json()["status"] == "failed"
    assert retried.json()["status"] == "executed"
    assert len(attempts) == 2


@pytest.mark.asyncio
async def test_yolo_still_deduplicates(gateway) -> None:
    client, runtime, sent = gateway
    runtime.set_yolo(True)
    args = {"to": "alex@example.com", "body": "hi"}
    async with client:
        await client.post("/tools/send_email", json={"arguments": args})
        repeat = await client.post("/tools/send_email", json={"arguments": args})

    # YOLO removes the prompt, never the safety rails.
    assert repeat.json()["deduplicated"] is True
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_deduplication_is_audited(gateway) -> None:
    client, runtime, _ = gateway
    args = {"to": "alex@example.com", "body": "hi"}
    async with client:
        first = await client.post("/tools/send_email", json={"arguments": args})
        await approve(client, first.json()["token"], args)
        await client.post("/tools/send_email", json={"arguments": args})

    records = [json.loads(line) for line in runtime.audit_path.read_text().splitlines()]
    assert records[-1]["event"] == "deduplicated"
    assert records[-1]["tool"] == "send_email"
