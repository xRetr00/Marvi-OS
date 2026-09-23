"""Opt-outs at the HTTP, journal, scheduler and playback boundaries."""

import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from marvi_gateway import context_policy as policy
from marvi_gateway.announce import Announcer
from marvi_gateway.app import create_app
from marvi_gateway.initiative import Initiative
from marvi_gateway.journal import EventJournal
from marvi_gateway.mind import Mind
from marvi_gateway.plugins import context_lines
from marvi_gateway.providers import config
from marvi_gateway.tools import ToolRegistry


@pytest.fixture(autouse=True)
def preferences(monkeypatch):
    for key in policy.SETTINGS:
        monkeypatch.setenv(key, "true")


@pytest.mark.parametrize("source", policy.SOURCES)
def test_source_opt_out_is_independent_and_persistent(source, monkeypatch, tmp_path):
    key = f"MARVI_CONTEXT_MIND_{source.upper()}"
    path = tmp_path / "providers.env"
    config.update({key: "false"}, path)
    assert not policy.allows(source, "mind")
    assert policy.allows(source, "prompt")
    # A saved user choice must survive an inherited launch default.
    monkeypatch.setenv(key, "true")
    config.load_into_environ(path)
    assert not policy.allows(source, "mind")
    config.update({key: "true"}, path)
    assert policy.allows(source, "mind")


def test_disabled_source_never_enters_journal_and_old_pending_is_not_deliberated(tmp_path, monkeypatch):
    journal = EventJournal(tmp_path / "events.db")
    try:
        journal.append("weather", "rain", "Rain soon")
        calls = []
        mind = Mind(journal, deliberate=lambda *args: calls.append(args))
        monkeypatch.setenv("MARVI_CONTEXT_MIND_WEATHER", "false")
        assert journal.append("weather", "snow", "Snow soon") is None
        assert mind.tick()["decisions"] == []
        assert calls == []
        assert journal.count_pending() == 1
        monkeypatch.setenv("MARVI_CONTEXT_MIND_WEATHER", "true")
        assert journal.append("weather", "snow", "Snow soon") is not None
    finally:
        journal.close()


@pytest.mark.parametrize("source", ["room", "vision", "map"])
def test_mixed_room_context_never_bypasses_an_opt_out(source, monkeypatch):
    calls = []
    plugin = SimpleNamespace(name="smart_room", context=SimpleNamespace(
        context_providers={"room": lambda: calls.append(True) or "room camera phone"}))
    assert context_lines([plugin]) == ["room camera phone"]
    monkeypatch.setenv(f"MARVI_CONTEXT_PROMPT_{source.upper()}", "false")
    assert context_lines([plugin]) == []
    assert len(calls) == 1
    # Prompt opt-out doesn't silently turn off the independent Mind feed.
    assert policy.event_allowed("room", "room_entry")
    monkeypatch.setenv(f"MARVI_CONTEXT_MIND_{source.upper()}", "false")
    assert not policy.event_allowed("room", "room_entry")


def test_master_off_stops_real_scheduler_and_blocks_manual_ticks(tmp_path, monkeypatch):
    from marvi_gateway.focus import Focus

    journal = EventJournal(tmp_path / "events.db")
    initiative = Initiative(Mind(journal), journal,
                            room_state=lambda: pytest.fail("read room while Mind off"))
    initiative.focus = Focus()
    initiative.focus._heavy = "game.exe"
    initiative.focus.hold(True)
    try:
        assert initiative.start()
        monkeypatch.setenv("MARVI_MIND_ENABLED", "false")
        initiative.stop(wait=True)
        assert not initiative.status()["running"]
        assert not initiative.focus.as_dict()["automatic"]
        assert initiative.focus.as_dict()["by_hand"]
        assert not initiative.start()
        assert initiative.run_mind()["considered"] == 0
        assert journal.append("system", "alarm", "ignored") is None
        initiative._guard("mind", lambda: pytest.fail("ran while off"))()
        monkeypatch.setenv("MARVI_MIND_ENABLED", "true")
        assert initiative.start()
        assert initiative.status()["running"]
    finally:
        initiative.stop(wait=True)
        journal.close()


def test_http_switch_stops_playback_unloads_model_and_persists(monkeypatch):
    started = threading.Event()
    class Player:
        def play(self, _pcm, _rate, cancelled):
            started.set()
            assert cancelled.wait(5)
            return False
    voice = Announcer(player=Player())
    monkeypatch.setattr(voice, "synthesize", lambda _: (b"\x00\x00", 24000))
    voice._model = object()
    app = create_app(tools=ToolRegistry(), announcer_service=voice)
    client = TestClient(app)
    result = {}
    thread = threading.Thread(target=lambda: result.update(voice.speak("Test")))
    thread.start()
    assert started.wait(5)
    response = client.put("/providers/settings", json={"values": {"MARVI_MIND_ENABLED": "false"}})
    thread.join(5)
    assert response.status_code == 200
    assert response.json()["settings"]["MARVI_MIND_ENABLED"] == "false"
    assert config.read()["MARVI_MIND_ENABLED"] == "false"
    assert result["cancelled"]
    assert voice.cold
    assert not voice.speak("Must stay silent")["played"]
    assert client.get("/memory/recall", params={"text": "hello"}).json() == {"block": ""}


def test_http_rejects_invalid_switch_without_saving():
    client = TestClient(create_app(tools=ToolRegistry()))
    response = client.put("/providers/settings", json={"values": {"MARVI_MIND_ENABLED": "maybe"}})
    assert response.status_code == 422
    assert "MARVI_MIND_ENABLED" not in config.read()


def test_http_power_switch_reconciles_real_initiative(monkeypatch):
    from marvi_gateway import app as app_module

    instances = []
    def build(*args, **kwargs):
        instance = Initiative(*args, **kwargs)
        instances.append(instance)
        return instance
    monkeypatch.setattr(app_module, "Initiative", build)
    client = TestClient(create_app())
    initiative = instances[0]
    try:
        for value in ("false", "true", "false"):
            response = client.put("/providers/settings", json={"values": {"MARVI_MIND_ENABLED": value}})
            assert response.status_code == 200
            assert initiative.status()["running"] == (value == "true")
    finally:
        initiative.stop(wait=True)


def test_voice_context_endpoint_filters_before_reading(monkeypatch):
    from marvi_gateway import app as app_module
    monkeypatch.setenv("MARVI_CONTEXT_PROMPT_MEMORY", "false")
    monkeypatch.setenv("MARVI_CONTEXT_PROMPT_CONTINUITY", "false")
    monkeypatch.setenv("MARVI_CONTEXT_PROMPT_SKILLS", "false")
    monkeypatch.setattr(app_module.standing, "block", lambda: pytest.fail("read memory"))
    monkeypatch.setattr(app_module.continuity, "block", lambda: pytest.fail("read continuity"))
    client = TestClient(create_app(tools=ToolRegistry()))
    response = client.get("/context")
    assert response.status_code == 200
    assert response.json()["memory_allowed"] is False


def test_chat_does_not_reinject_recalled_memory_or_curiosity(monkeypatch, tmp_path):
    from marvi_gateway.chat import Chat, ChatStore
    monkeypatch.setenv("MARVI_CONTEXT_PROMPT_MEMORY", "false")
    monkeypatch.setenv("MARVI_CONTEXT_PROMPT_CONTINUITY", "false")
    monkeypatch.setenv("MARVI_CONTEXT_PROMPT_MIND", "false")
    store = ChatStore(tmp_path / "chat.db")
    try:
        chat = Chat(store=store, curiosity=SimpleNamespace(guidance=lambda _: pytest.fail("read curiosity")))
        block = chat._volatile_context(recalled="private-memory", summary="private-summary")
        assert "private-memory" not in block
        assert "private-summary" not in block
    finally:
        store.close()


def test_preferences_survive_a_real_gateway_process_restart(tmp_path):
    """Loopback HTTP and disk persistence, no live user services or inference."""
    @contextmanager
    def gateway():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        code = (
            "import uvicorn; from marvi_gateway.app import create_app; "
            "from marvi_gateway.tools import ToolRegistry; "
            f"uvicorn.run(create_app(tools=ToolRegistry()), host='127.0.0.1', port={port}, "
            "lifespan='off', log_level='error')"
        )
        env = {**os.environ, "MARVI_HOME": str(tmp_path / "child"),
               "MARVI_LOG_DIR": str(tmp_path / "child" / "logs"),
               "MARVI_MIND_ENABLED": "true"}
        process = subprocess.Popen([sys.executable, "-c", code], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
                deadline = time.monotonic() + 20
                while True:
                    try:
                        if client.get("/context").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    assert process.poll() is None, "Gateway exited before listening"
                    assert time.monotonic() < deadline, "Gateway never became ready"
                    time.sleep(0.05)
                yield client
        finally:
            process.terminate()
            process.wait(timeout=10)

    changes = {"MARVI_MIND_ENABLED": "false", "MARVI_CONTEXT_PROMPT_MEMORY": "false"}
    with gateway() as client:
        response = client.put("/providers/settings", json={"values": changes})
        assert response.status_code == 200
        assert client.get("/context").json()["memory_allowed"] is False
    with gateway() as client:
        saved = client.get("/providers").json()["settings"]
        assert all(saved[key] == value for key, value in changes.items())
        assert client.get("/context").json()["memory_allowed"] is False
        assert client.put("/providers/settings", json={"values": {
            "MARVI_MIND_ENABLED": "true", "MARVI_CONTEXT_PROMPT_MEMORY": "true"
        }}).status_code == 200
        assert client.get("/context").json()["memory_allowed"] is True
