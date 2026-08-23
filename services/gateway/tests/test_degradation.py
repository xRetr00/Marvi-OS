"""What still works when something is broken.

The rule this phase is built on: **a failed subsystem degrades, it does not
cascade.** No vision must not stop voice. No provider must not stop the room
tools — a light switch does not need a model. And whatever is broken, the
Gateway must stay up and stay honest about it, because a shell polling a dead
server is exactly the symptom that started Phase 10.

Each test kills one thing and asserts the rest survives.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from marvi_gateway.app import create_app
from marvi_gateway.tools import ToolRegistry, ToolSpec


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVI_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("MARVI_PROVIDER_CONFIG", str(tmp_path / "providers.env"))
    monkeypatch.setenv("MARVI_IDENTITY_DIR", str(tmp_path / "identity"))
    monkeypatch.setenv("MARVI_TOKEN_STORE", str(tmp_path / "tokens.bin"))
    monkeypatch.setenv("MARVI_JOURNAL_DB", str(tmp_path / "journal.sqlite3"))
    monkeypatch.setenv("MARVI_CHAT_DB", str(tmp_path / "chat.sqlite3"))
    monkeypatch.setenv("MARVI_PLUGIN_DATA", str(tmp_path / "plugin-data"))
    return tmp_path


def tools_with_a_light() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="set_light",
            description="Set the light",
            arguments={"on": bool},
            sensitive=False,
            handler=lambda on: {"ok": on},
        )
    )
    return registry


# -- no provider ---------------------------------------------------------------


def test_without_a_provider_the_gateway_still_serves(isolated, monkeypatch) -> None:
    monkeypatch.setattr(
        "marvi_gateway.providers.base.configured_profiles", lambda: []
    )
    with TestClient(create_app(tools=tools_with_a_light())) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/tools").status_code == 200
        assert client.get("/doctor").status_code == 200


def test_without_a_provider_the_room_tools_still_work(isolated) -> None:
    with TestClient(create_app(tools=tools_with_a_light())) as client:
        result = client.post("/tools/set_light", json={"arguments": {"on": True}}).json()

    # A light switch does not need a model.
    assert result["status"] == "executed"


def test_without_a_provider_chat_says_so_rather_than_erroring(isolated, monkeypatch) -> None:
    monkeypatch.setattr(
        "marvi_gateway.providers.ProviderClient.candidates", lambda self, preferred=None: []
    )
    with TestClient(create_app()) as client:
        body = client.post("/chat", json={"message": "hello"}).json()

    assert body["error"]
    assert "provider" in body["error"].lower()


def test_without_a_provider_the_mind_stays_deterministic(isolated, monkeypatch) -> None:
    monkeypatch.setattr("marvi_gateway.deliberate.configured_profiles", lambda: [])
    from marvi_gateway.deliberate import deliberator_from_env

    # The policy still decides; it just stops asking a model to phrase things.
    assert deliberator_from_env() is None


# -- no room sidecar -------------------------------------------------------------


def test_a_dead_sidecar_does_not_take_the_gateway_with_it(isolated, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_ROOM_PORT", "59998")  # nothing listening
    with TestClient(create_app()) as client:
        health = client.get("/health").json()

    assert health["state"] in ("ready", "degraded", "starting")
    assert health["components"]["gateway"]["state"] == "ready"


def test_a_dead_sidecar_is_reported_not_hidden(isolated, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_ROOM_PORT", "59998")
    with TestClient(create_app()) as client:
        room = client.get("/health").json()["components"]["room"]

    assert room["state"] != "ready"
    assert room["detail"]


# -- no vision --------------------------------------------------------------------


def test_without_room_vision_everything_else_is_unaffected(isolated) -> None:
    with TestClient(create_app(tools=tools_with_a_light())) as client:
        health = client.get("/health").json()

        assert health["components"]["vision"]["state"] == "offline"
        # Vision is the most optional thing in the system.
        assert health["components"]["gateway"]["state"] == "ready"
        assert (
            client.post("/tools/set_light", json={"arguments": {"on": False}}).json()["status"]
            == "executed"
        )


def test_vision_health_comes_from_the_room_sidecars_snapshot(isolated) -> None:
    home = isolated / "plugin-data" / "smart_room"
    home.mkdir(parents=True)
    (home / "state.json").write_text(
        json.dumps(
            {
                "vision": {
                    "enabled": True,
                    "running": True,
                    "camera_open": True,
                    "stale": False,
                    "person_count": 1,
                    "owner_visible": True,
                }
            }
        ),
        encoding="utf-8",
    )

    with TestClient(create_app()) as client:
        vision = client.get("/health").json()["components"]["vision"]

    assert vision["state"] == "ready"
    assert "owner visible" in vision["detail"]


# -- broken storage -----------------------------------------------------------------


def test_a_corrupt_journal_is_a_finding_not_a_crash(isolated) -> None:
    (isolated / "journal.sqlite3").write_bytes(b"not a database at all")

    # Starting must not depend on every file on disk being intact.
    with TestClient(create_app(tools=ToolRegistry())) as client:
        report = client.get("/doctor").json()

    journal = next(f for f in report["findings"] if f["check"] == "journal")
    assert journal["status"] == "fail"
    assert journal["remedy"]["runnable"] is True


def test_an_unreadable_token_store_does_not_stop_startup(isolated) -> None:
    (isolated / "tokens.bin").write_bytes(b"written by another windows account")

    with TestClient(create_app(tools=ToolRegistry())) as client:
        assert client.get("/health").status_code == 200
        # And it reads as "reconnect", not as a hard failure.
        rows = {p["name"]: p for p in client.get("/providers").json()["providers"]}
        assert rows["codex"]["oauth"]["connected"] is False


# -- broken logging ---------------------------------------------------------------


def test_logging_failure_does_not_break_a_request(isolated, monkeypatch) -> None:
    from marvi_gateway import logs

    monkeypatch.setattr(
        logs.SubsystemRouter, "emit", lambda self, record: (_ for _ in ()).throw(OSError("disk"))
    )
    with TestClient(create_app(tools=tools_with_a_light())) as client:
        # Logging must never become the failure it was meant to explain.
        assert client.get("/health").status_code == 200


# -- everything at once -------------------------------------------------------------


def test_with_nothing_configured_marvi_still_explains_itself(isolated, monkeypatch) -> None:
    monkeypatch.setattr("marvi_gateway.providers.base.configured_profiles", lambda: [])
    monkeypatch.setenv("MARVI_ROOM_PORT", "59998")

    with TestClient(create_app(tools=ToolRegistry())) as client:
        assert client.get("/health").status_code == 200
        report = client.get("/doctor").json()
        text = client.get("/doctor/diagnostics").json()["text"]

    # The worst case still produces something a person can act on.
    assert report["summary"]["fail"] + report["summary"]["warn"] > 0
    assert "## Findings" in text
    for finding in report["findings"]:
        if finding["status"] != "ok":
            assert finding["remedy"]["kind"] != "none", finding["check"]
