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


# -- a copied picture, and the speaker's actual level -------------------------


class FakeVision:
    """Stands in for the vision role, and records what it was handed."""

    def __init__(self) -> None:
        self.saw_image = False

    def call_with_fallback(self, messages, **_kwargs):
        self.saw_image = any(
            part.get("type") == "image" for part in messages[-1]["content"]
        )

        class Answer:
            text = "A screenshot of a stack trace."

        return Answer()


def test_a_copied_picture_comes_back_as_words(monkeypatch) -> None:
    vision = FakeVision()
    monkeypatch.setattr(desk, "read_text", lambda: "")
    monkeypatch.setattr(desk, "read_image", lambda: b"pretend-png")
    registry = ToolRegistry()
    desk.register_desk_tools(registry, vision)

    result = registry.execute(registry.get("clipboard_read"), {})

    assert vision.saw_image is True
    assert result["kind"] == "image"
    # The picture is external content, like a web page or a file.
    assert "UNTRUSTED" in str(result["text"]).upper()
    assert "stack trace" in str(result["text"])


def test_an_empty_clipboard_still_says_so(monkeypatch) -> None:
    monkeypatch.setattr(desk, "read_text", lambda: "")
    monkeypatch.setattr(desk, "read_image", lambda: None)
    registry = ToolRegistry()
    desk.register_desk_tools(registry, FakeVision())

    assert registry.execute(registry.get("clipboard_read"), {})["empty"] is True


def test_a_picture_with_no_vision_model_says_which_setting(monkeypatch) -> None:
    monkeypatch.setattr(desk, "read_text", lambda: "")
    monkeypatch.setattr(desk, "read_image", lambda: b"png")
    registry = ToolRegistry()
    desk.register_desk_tools(registry, None)

    assert "Settings > Models" in registry.execute(registry.get("clipboard_read"), {})["error"]


def test_the_volume_can_be_read_and_set_outright(monkeypatch) -> None:
    speaker = {"level": 26, "muted": False}
    monkeypatch.setattr(desk, "volume_now", lambda: dict(speaker))
    monkeypatch.setattr(
        desk, "set_volume", lambda percent: speaker.update(level=percent) or dict(speaker)
    )
    registry = ToolRegistry()
    desk.register_desk_tools(registry)

    assert registry.execute(registry.get("media_status"), {}) == {"level": 26, "muted": False}

    control = registry.get("media_control")
    assert registry.execute(control, {"action": "volume_set", "level": 30})["volume"] == 30
    assert speaker["level"] == 30
    # A level with any volume action means "set it there", not "press a key".
    assert registry.execute(control, {"action": "volume_up", "level": 55})["volume"] == 55
    assert registry.execute(control, {"action": "volume_set"})["error"].endswith("0 to 100")


def test_the_dib_a_windows_screenshot_puts_on_the_clipboard_becomes_a_png() -> None:
    """The header Windows leaves off is the whole conversion."""
    import io as _io

    from PIL import Image

    original = Image.new("RGB", (8, 4), "white")
    whole = _io.BytesIO()
    original.save(whole, "BMP")
    dib = whole.getvalue()[14:]

    class FakeUser32:
        def IsClipboardFormatAvailable(self, _format):  # noqa: N802 - Win32 name
            return 1

        def OpenClipboard(self, _owner):  # noqa: N802
            return 1

        def GetClipboardData(self, _format):  # noqa: N802
            return 1

        def CloseClipboard(self):  # noqa: N802
            return 1

    import ctypes

    buffer = ctypes.create_string_buffer(dib)

    class FakeKernel32:
        def GlobalSize(self, _handle):  # noqa: N802
            return len(dib)

        def GlobalLock(self, _handle):  # noqa: N802
            return ctypes.addressof(buffer)

        def GlobalUnlock(self, _handle):  # noqa: N802
            return 1

    import marvi_gateway.desk as desk_module

    original_win32 = desk_module._win32
    desk_module._win32 = lambda: (FakeUser32(), FakeKernel32())
    try:
        png = desk.read_image()
    finally:
        desk_module._win32 = original_win32

    with Image.open(_io.BytesIO(png)) as back:
        assert back.format == "PNG" and back.size == (8, 4)
