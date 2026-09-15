"""The clipboard and the media keys, without touching this machine's own."""

from __future__ import annotations

import pytest

from marvi_gateway import desk
from marvi_gateway.tools import ToolRegistry


@pytest.fixture
def registry(monkeypatch):
    held = {"text": "copied words"}
    pressed: list[int] = []
    monkeypatch.setattr(desk, "read_text", lambda: held["text"])
    monkeypatch.setattr(desk, "write_text", lambda text: held.update(text=text))
    monkeypatch.setattr(desk, "press", pressed.append)
    registry = ToolRegistry()
    desk.register_desk_tools(registry)
    registry.held, registry.pressed = held, pressed  # type: ignore[attr-defined]
    return registry


def call(registry, name, **arguments):
    spec = registry.get(name)
    return registry.execute(spec, registry.validate(spec, arguments))


def test_the_clipboard_comes_back_enveloped_and_goes_back_verbatim(registry) -> None:
    read = call(registry, "clipboard_read")
    assert read["chars"] == len("copied words")
    assert "copied words" in str(read["text"]) and read["text"] != "copied words"

    assert call(registry, "clipboard_write", text="paste me")["copied"] is True
    assert registry.held["text"] == "paste me"


def test_an_empty_clipboard_says_so(registry) -> None:
    registry.held["text"] = ""
    assert call(registry, "clipboard_read")["empty"] is True


def test_only_the_volume_keys_repeat(registry) -> None:
    assert call(registry, "media_control", action="volume_up", steps=5)["times"] == 5
    assert call(registry, "media_control", action="next", steps=5)["times"] == 1
    assert call(registry, "media_control", action="volume_down", steps=999)["times"] == desk.MAX_STEPS
    assert registry.pressed[:6] == [desk.MEDIA_KEYS["volume_up"]] * 5 + [desk.MEDIA_KEYS["next"]]


def test_an_unknown_key_is_refused_with_the_list(registry) -> None:
    result = call(registry, "media_control", action="louder")
    assert "play_pause" in result["error"] and not registry.pressed


def test_none_of_them_asks_for_confirmation(registry) -> None:
    assert not any(registry.get(n).sensitive for n in ("clipboard_read", "clipboard_write", "media_control"))
