import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.app import create_app
from marvi_gateway.runtime import AssistantState, ConfirmationRequest, RuntimeStore


@pytest.mark.asyncio
async def test_health_exposes_branding_version_and_component_readiness() -> None:
    transport = ASGITransport(app=create_app(version="0.1.0-test"))
    async with AsyncClient(transport=transport, base_url="http://marvi.local") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["product"] == "Marvi OS"
    assert payload["version"] == "0.1.0-test"
    assert payload["components"]["gateway"]["state"] == "ready"
    assert payload["components"]["livekit"]["state"] == "pending"
    assert payload["components"]["voice"]["state"] == "starting"
    assert payload["assistant"]["phase"] == "ready"


@pytest.mark.asyncio
async def test_livekit_session_issues_local_room_credentials() -> None:
    transport = ASGITransport(app=create_app(version="0.1.0-test"))
    async with AsyncClient(transport=transport, base_url="http://marvi.local") as client:
        response = await client.post("/livekit/session")

    assert response.status_code == 200
    payload = response.json()
    assert payload["url"] == "ws://127.0.0.1:7880"
    assert payload["room"] == "marvi-os-local"
    assert payload["token"].count(".") == 2


@pytest.mark.asyncio
async def test_runtime_mode_is_gateway_authoritative() -> None:
    transport = ASGITransport(app=create_app(version="0.1.0-test"))
    async with AsyncClient(transport=transport, base_url="http://marvi.local") as client:
        response = await client.put("/runtime/mode", json={"yolo": True})
        follow_up = await client.get("/runtime")

    assert response.status_code == 200
    assert response.json()["assistant"]["yolo"] is True
    assert follow_up.json()["assistant"]["yolo"] is True


@pytest.mark.asyncio
async def test_confirmation_requires_exact_gateway_token() -> None:
    runtime = RuntimeStore()
    runtime.assistant = AssistantState(
        phase="confirmation",
        caption="Confirm action",
        confirmation=ConfirmationRequest(
            token="confirm-123", action="Turn off the room light", detail="Bedroom bulb"
        ),
    )
    transport = ASGITransport(app=create_app(version="0.1.0-test", runtime=runtime))
    async with AsyncClient(transport=transport, base_url="http://marvi.local") as client:
        rejected = await client.post("/confirmations/wrong", json={"decision": "approve"})
        approved = await client.post(
            "/confirmations/confirm-123", json={"decision": "approve"}
        )

    assert rejected.status_code == 404
    assert approved.status_code == 200
    assert approved.json()["assistant"]["phase"] == "notification"
    assert approved.json()["assistant"]["confirmation"] is None
