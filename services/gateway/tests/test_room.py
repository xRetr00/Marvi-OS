"""Room sidecar tests.

These run a real newline-delimited JSON-RPC server on loopback rather than
patching the transport, so the framing, auth field, and failure modes are
exercised the same way the live runtime exercises them.
"""

from __future__ import annotations

import json
import socket
import threading

import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.app import create_app
from marvi_gateway.room import (
    RoomRejectedError,
    RoomSidecar,
    RoomUnavailableError,
    register_room_tools,
)
from marvi_gateway.runtime import RuntimeStore
from marvi_gateway.tools import ToolRegistry

TOKEN = "test-rpc-token"


class FakeSidecar:
    """Minimal stand-in speaking the runtime's actual wire contract."""

    def __init__(self, home, responder=None):
        self.home = home
        self.requests: list[dict] = []
        self._responder = responder or self._default_responder
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(8)
        self.port = self._server.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        (home / ".rpc-token").write_text(TOKEN, encoding="utf-8")

    @staticmethod
    def _default_responder(request):
        method = request["method"]
        if method == "ping":
            return {"success": True}
        if method == "get_state":
            return {"success": True, "state": {"light": {"on": True}, "modes": {"active_mode": "focus"}}}
        if method == "get_health":
            return {"success": True, "health": {"devices": {"tuya_bulb": {"online": True}}}}
        if method in {"set_mode", "set_light"}:
            return {"success": True, "applied": request["params"]}
        return {"success": False, "error": f"unknown method: {method}"}

    def start(self):
        self._thread.start()
        return self

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            with conn:
                buffer = b""
                while b"\n" not in buffer:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk
                if not buffer:
                    continue
                request = json.loads(buffer.decode("utf-8").strip())
                self.requests.append(request)
                if request.get("auth") != TOKEN:
                    payload = {"jsonrpc": "2.0", "id": request.get("id"), "error": "unauthorized"}
                else:
                    result = self._responder(request)
                    payload = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "result": {
                            "schema_version": 1,
                            "request_id": request.get("id"),
                            "status": "success" if result.get("success") else "failed",
                            **result,
                        },
                    }
                conn.sendall(json.dumps(payload).encode("utf-8") + b"\n")

    def stop(self):
        self._stop.set()
        self._server.close()
        self._thread.join(timeout=2)


@pytest.fixture
def sidecar(tmp_path):
    fake = FakeSidecar(tmp_path).start()
    client = RoomSidecar(port=fake.port, home=tmp_path, timeout=2.0)
    yield fake, client
    fake.stop()


def test_call_sends_the_authenticated_wire_contract(sidecar) -> None:
    fake, client = sidecar
    result = client.call("set_mode", {"mode": "focus"})

    assert result["success"] is True
    request = fake.requests[-1]
    assert request["jsonrpc"] == "2.0"
    assert request["auth"] == TOKEN
    assert request["method"] == "set_mode"
    assert request["params"] == {"mode": "focus"}
    assert request["id"]


def test_sidecar_refusal_is_a_decision_not_an_outage(sidecar) -> None:
    _, client = sidecar
    with pytest.raises(RoomRejectedError):
        client.call("no_such_method", {})


def test_missing_token_is_reported_as_unavailable(tmp_path) -> None:
    client = RoomSidecar(port=1, home=tmp_path, timeout=0.5)
    with pytest.raises(RoomUnavailableError):
        client.call("ping")


def test_dead_sidecar_is_unavailable_not_a_crash(sidecar) -> None:
    fake, client = sidecar
    fake.stop()

    assert client.reachable() is False
    with pytest.raises(RoomUnavailableError):
        client.call("ping")


def test_state_falls_back_to_the_disk_snapshot_while_the_sidecar_is_down(
    sidecar, tmp_path
) -> None:
    fake, client = sidecar
    (tmp_path / "state.json").write_text(
        json.dumps({"light": {"on": False}, "modes": {"active_mode": "sleep"}}), encoding="utf-8"
    )
    live = client.state()
    fake.stop()
    stale = client.state()

    assert live["live"] is True
    assert live["state"]["modes"]["active_mode"] == "focus"
    assert stale["live"] is False
    assert stale["stale"] is True
    assert stale["state"]["modes"]["active_mode"] == "sleep"


def test_reconnect_after_restart_returns_to_live_reads(tmp_path) -> None:
    fake = FakeSidecar(tmp_path).start()
    client = RoomSidecar(port=fake.port, home=tmp_path, timeout=2.0)
    assert client.reachable() is True
    fake.stop()
    assert client.reachable() is False

    restarted = FakeSidecar(tmp_path)
    restarted._server.close()
    restarted._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    restarted._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    restarted._server.bind(("127.0.0.1", fake.port))
    restarted._server.listen(8)
    restarted.start()
    try:
        assert client.reachable() is True
        assert client.state()["live"] is True
    finally:
        restarted.stop()


@pytest.mark.asyncio
async def test_room_write_needs_confirmation_and_reaches_the_sidecar(
    sidecar, tmp_path
) -> None:
    fake, client = sidecar
    registry = ToolRegistry()
    register_room_tools(registry, client)
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    app = create_app(version="0.1.0-test", runtime=runtime, tools=registry)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://marvi.local"
    ) as http:
        requested = await http.post(
            "/tools/room_set_light", json={"arguments": {"on": True, "brightness": 30}}
        )
        token = requested.json()["token"]
        approved = await http.post(
            f"/confirmations/{token}",
            json={"decision": "approve", "arguments": {"on": True, "brightness": 30}},
        )

    assert requested.json()["status"] == "confirmation_required"
    assert approved.json()["status"] == "executed"
    assert fake.requests[-1]["method"] == "set_light"
    assert fake.requests[-1]["params"] == {"on": True, "brightness": 30}


@pytest.mark.asyncio
async def test_room_read_is_not_gated_and_survives_sidecar_death(sidecar, tmp_path) -> None:
    fake, client = sidecar
    registry = ToolRegistry()
    register_room_tools(registry, client)
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    app = create_app(version="0.1.0-test", runtime=runtime, tools=registry)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://marvi.local"
    ) as http:
        live = await http.post("/tools/room_state", json={"arguments": {}})
        fake.stop()
        dead = await http.post("/tools/room_state", json={"arguments": {}})
        still_serving = await http.get("/health")

    assert live.json()["status"] == "executed"
    assert dead.json()["status"] == "failed"
    assert "not reachable" in dead.json()["error"]
    assert still_serving.status_code == 200
    assert still_serving.json()["assistant"]["phase"] == "ready"


@pytest.mark.asyncio
async def test_invalid_room_arguments_never_reach_the_sidecar(sidecar, tmp_path) -> None:
    fake, client = sidecar
    registry = ToolRegistry()
    register_room_tools(registry, client)
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    runtime.set_yolo(True)
    app = create_app(version="0.1.0-test", runtime=runtime, tools=registry)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://marvi.local"
    ) as http:
        bad_mode = await http.post(
            "/tools/room_set_mode", json={"arguments": {"mode": "self_destruct"}}
        )
        bad_brightness = await http.post(
            "/tools/room_set_light", json={"arguments": {"on": True, "brightness": 900}}
        )
        wrong_type = await http.post(
            "/tools/room_set_light", json={"arguments": {"on": "yes"}}
        )

    assert bad_mode.json()["status"] == "failed"
    assert bad_brightness.json()["status"] == "failed"
    assert wrong_type.status_code == 422
    assert [request["method"] for request in fake.requests] == []
