import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.app import create_app
from marvi_gateway.runtime import RuntimeStore
from marvi_gateway.tools import ToolRegistry, ToolSpec


class FakeOneShot:
    voice = "alba"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.stopped = False

    def speak(self, text: str, purpose: str = "proactive") -> dict:
        self.calls.append((text, purpose))
        return {"played": True, "cancelled": False, "seconds": 0.25}

    def stop(self) -> bool:
        self.stopped = True
        return True

    def close(self) -> None:
        return None


async def health(monkeypatch, livekit_running: bool) -> dict:
    # Pin the probe. Reading the real port asserts a fact about the developer's
    # machine rather than about the code, and passes or fails depending on
    # whether LiveKit happens to be up.
    monkeypatch.setattr("marvi_gateway.app.livekit_is_ready", lambda *a, **k: livekit_running)
    transport = ASGITransport(app=create_app(version="0.1.0-test"))
    async with AsyncClient(transport=transport, base_url="http://marvi.local") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_health_exposes_branding_version_and_component_readiness(monkeypatch) -> None:
    payload = await health(monkeypatch, livekit_running=False)

    assert payload["product"] == "Marvi OS"
    assert payload["version"] == "0.1.0-test"
    assert payload["components"]["gateway"]["state"] == "ready"
    assert payload["components"]["livekit"]["state"] == "pending"
    assert payload["assistant"]["phase"] == "ready"


@pytest.mark.asyncio
async def test_voice_reports_why_it_is_not_ready_rather_than_a_fixed_state(monkeypatch) -> None:
    """It used to answer `starting` / "native streaming worker available" always.

    A component state that never changes is not a state, and it is what made
    `VOICE STARTING` in the status bar mean nothing. With no LiveKit server
    there can be no session, and saying so is more useful than saying anything
    about a worker.
    """
    payload = await health(monkeypatch, livekit_running=False)
    voice = payload["components"]["voice"]

    assert voice["state"] == "pending"
    assert "LiveKit" in voice["detail"]


@pytest.mark.asyncio
async def test_a_running_livekit_server_reports_ready(monkeypatch) -> None:
    payload = await health(monkeypatch, livekit_running=True)

    assert payload["components"]["livekit"]["state"] == "ready"


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
async def test_read_aloud_uses_one_shot_speech_not_a_livekit_room() -> None:
    speech = FakeOneShot()
    app = create_app(tools=ToolRegistry(), announcer_service=speech)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://marvi.local") as client:
        response = await client.post("/speech/read-aloud", json={"text": "Read this."})
        stopped = await client.post("/speech/stop")

    assert response.status_code == 200
    assert response.json()["played"] is True
    assert speech.calls == [("Read this.", "read_aloud")]
    assert stopped.json() == {"stopped": True}


@pytest.mark.asyncio
async def test_voice_session_state_suppresses_proactive_speech() -> None:
    app = create_app(tools=ToolRegistry(), announcer_service=FakeOneShot())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://marvi.local") as client:
        active = await client.post("/voice/session-state", json={"active": True})
        inactive = await client.post("/voice/session-state", json={"active": False})

    assert active.json() == {"conversation_active": True}
    assert inactive.json() == {"conversation_active": False}


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
async def test_confirmation_requires_exact_gateway_token(tmp_path) -> None:
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            name="room_set_mode",
            description="Turn off the room light",
            arguments={"mode": str},
            sensitive=True,
            handler=lambda **args: args,
        )
    )
    transport = ASGITransport(
        app=create_app(version="0.1.0-test", runtime=runtime, tools=tools)
    )
    async with AsyncClient(transport=transport, base_url="http://marvi.local") as client:
        requested = await client.post(
            "/tools/room_set_mode", json={"arguments": {"mode": "off"}}
        )
        token = requested.json()["token"]
        rejected = await client.post(
            "/confirmations/wrong", json={"decision": "approve", "arguments": {"mode": "off"}}
        )
        approved = await client.post(
            f"/confirmations/{token}",
            json={"decision": "approve", "arguments": {"mode": "off"}},
        )

    assert rejected.status_code == 404
    assert approved.status_code == 200
    assert approved.json()["status"] == "executed"
    assert approved.json()["runtime"]["assistant"]["phase"] == "notification"
    assert approved.json()["runtime"]["assistant"]["confirmation"] is None
