"""One switch that keeps everything on this machine."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway import privacy
from marvi_gateway.providers.client import local_only
from marvi_gateway.runtime import RuntimeStore
from marvi_gateway.tools import ToolBlockedError, ToolRegistry, ToolSpec


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for name in ("web_search", "send_email", "telegram_send", "file_read"):
        registry.register(ToolSpec(name, f"{name} for the test.", {}, False, lambda: "ran"))
    return registry


def test_it_refuses_what_leaves_and_allows_what_does_not(monkeypatch) -> None:
    registry = _registry()
    monkeypatch.setenv(privacy.SETTING, "1")

    for name in ("web_search", "send_email", "telegram_send"):
        with pytest.raises(ToolBlockedError, match="Privacy mode"):
            registry.execute(registry.get(name), {})
    # Local tools are untouched; privacy mode is not a mute button.
    assert registry.execute(registry.get("file_read"), {}) == "ran"


def test_off_is_the_way_it_always_was(monkeypatch) -> None:
    monkeypatch.delenv(privacy.SETTING, raising=False)
    registry = _registry()
    assert registry.execute(registry.get("web_search"), {}) == "ran"
    assert privacy.on() is False


def test_it_implies_local_only_models(monkeypatch) -> None:
    monkeypatch.delenv("MARVI_LOCAL_ONLY", raising=False)
    monkeypatch.setenv(privacy.SETTING, "1")
    assert local_only() is True


def test_hosted_memory_falls_back_to_the_local_store(monkeypatch, tmp_path) -> None:
    from marvi_gateway.memory_providers import PROVIDER_SETTING, MemoryRuntime

    monkeypatch.setenv(PROVIDER_SETTING, "honcho")
    runtime = MemoryRuntime()
    assert runtime.provider_name == "honcho"

    monkeypatch.setenv(privacy.SETTING, "1")
    assert runtime.provider_name == "local"


def test_an_update_check_does_not_phone_home(monkeypatch, tmp_path) -> None:
    from marvi_gateway import updates

    monkeypatch.setenv(privacy.SETTING, "1")
    answer = updates.check(tmp_path / "bootstrap.exe", tmp_path, "release")
    assert answer["ok"] is False and "Privacy mode" in answer["detail"]


def test_the_refusal_names_the_feature_and_the_way_back() -> None:
    said = privacy.refusal("accounts")
    assert "connected accounts" in said and "Settings > Preferences" in said
    assert privacy.feature_of("web_fetch") == "web"
    assert privacy.feature_of("room_set_light") == ""  # the room is local


def test_the_switch_is_remembered_and_shown(monkeypatch) -> None:
    monkeypatch.delenv(privacy.SETTING, raising=False)
    store = RuntimeStore()
    assert store.assistant.privacy is False

    store.set_privacy(True)
    assert store.assistant.privacy is True
    assert privacy.on() is True  # written to the environment, so it survives
    # And recorded, like every other change to how Marvi acts.
    assert any(getattr(event, "event", "") == "privacy_mode" for event in store.recent_audit())


@pytest.mark.asyncio
async def test_the_window_can_turn_it_on_and_off(monkeypatch) -> None:
    from marvi_gateway.app import create_app

    monkeypatch.delenv(privacy.SETTING, raising=False)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        on = await client.put("/runtime/mode", json={"privacy": True})
        assert on.json()["assistant"]["privacy"] is True
        # Sending only one switch leaves the other alone.
        assert on.json()["assistant"]["yolo"] is False

        off = await client.put("/runtime/mode", json={"privacy": False})
        assert off.json()["assistant"]["privacy"] is False
