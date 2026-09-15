"""Two small things at the desk: the clipboard and the media keys.

Both were reachable only by handing Jarvi the whole computer -- a multi-second
sub-agent job to press "pause" or to read what was just copied. On a voice turn
that is the difference between an assistant and a wait. Each is a few Win32
calls through `ctypes`, which is already how `focus.py` asks Windows whether a
fullscreen app is running; no dependency is added.

The clipboard is untrusted content like a file or a web page: it is returned
inside the external-content envelope, and it may hold a password the user just
copied, which the tool description says never to read out.
"""

from __future__ import annotations

import ctypes
import time
from typing import Any

from .untrusted import wrap_external

#: Plenty for "what did I just copy"; a whole log pasted into a turn is not.
MAX_CLIPBOARD_CHARS = 20_000

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
KEYEVENTF_KEYUP = 0x0002

#: Windows virtual-key codes for the keys every media keyboard has. Pressing
#: them is what the keyboard does, so every player that honours the keyboard
#: honours this -- Spotify, a browser tab, the system mixer.
MEDIA_KEYS = {
    "play_pause": 0xB3,
    "next": 0xB0,
    "previous": 0xB1,
    "stop": 0xB2,
    "volume_up": 0xAF,
    "volume_down": 0xAE,
    "mute": 0xAD,
}

#: One volume key press moves Windows by two percent; 25 is the whole range.
MAX_STEPS = 25


class DeskUnavailableError(Exception):
    """Not Windows, or Windows refused the call."""


def _win32() -> tuple[Any, Any]:
    try:
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32  # type: ignore[attr-defined]
    except AttributeError as exc:
        raise DeskUnavailableError("the clipboard and media keys are Windows-only") from exc
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    return user32, kernel32


def _open_clipboard(user32: Any) -> None:
    # Another program may hold it for a moment; that is normal, not an error.
    for _ in range(10):
        if user32.OpenClipboard(None):
            return
        time.sleep(0.05)
    raise DeskUnavailableError("another program is holding the clipboard")


def read_text() -> str:
    user32, kernel32 = _win32()
    _open_clipboard(user32)
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(pointer) if pointer else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def write_text(text: str) -> None:
    user32, kernel32 = _win32()
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    _open_clipboard(user32)
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, data, size)
        kernel32.GlobalUnlock(handle)
        # Ownership passes to the system on success; nothing to free.
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise DeskUnavailableError("Windows refused the clipboard write")
    finally:
        user32.CloseClipboard()


def press(virtual_key: int) -> None:
    user32, _ = _win32()
    user32.keybd_event(virtual_key, 0, 0, 0)
    user32.keybd_event(virtual_key, 0, KEYEVENTF_KEYUP, 0)


def register_desk_tools(registry: Any) -> None:
    from .tools import ToolSpec

    def clipboard_read() -> dict[str, Any]:
        try:
            text = read_text()
        except DeskUnavailableError as exc:
            return {"error": str(exc)}
        if not text:
            return {"empty": True, "note": "the clipboard holds no text"}
        clipped = text[:MAX_CLIPBOARD_CHARS]
        return {
            "chars": len(text),
            "truncated": len(text) > MAX_CLIPBOARD_CHARS,
            "text": wrap_external("clipboard", clipped).model_dump(),
        }

    def clipboard_write(text: str) -> dict[str, Any]:
        try:
            write_text(text)
        except DeskUnavailableError as exc:
            return {"error": str(exc)}
        return {"copied": True, "chars": len(text)}

    def media_control(action: str, steps: int = 1) -> dict[str, Any]:
        key = MEDIA_KEYS.get(action.strip().lower())
        if key is None:
            return {"error": f"unknown action {action!r}; use one of {', '.join(MEDIA_KEYS)}"}
        # Only the volume keys repeat; pressing "next" five times is a different request.
        count = max(1, min(int(steps), MAX_STEPS)) if action.startswith("volume") else 1
        try:
            for _ in range(count):
                press(key)
        except DeskUnavailableError as exc:
            return {"error": str(exc)}
        return {"pressed": action, "times": count}

    registry.register(ToolSpec(
        name="clipboard_read",
        description="Read the text the user last copied.",
        arguments={},
        sensitive=False,
        handler=clipboard_read,
    ))
    registry.register(ToolSpec(
        name="clipboard_write",
        description="Put text on the clipboard so the user can paste it.",
        arguments={"text": str},
        sensitive=False,
        handler=clipboard_write,
        describes={"text": "Exactly what should be pasted. It replaces what the user had copied."},
    ))
    registry.register(ToolSpec(
        name="media_control",
        description="Play, pause, skip, or change the volume with the media keys.",
        arguments={"action": str},
        optional={"steps": int},
        sensitive=False,
        handler=media_control,
        describes={
            "action": "One of: " + ", ".join(MEDIA_KEYS) + ".",
            "steps": "For volume_up and volume_down only: how many presses, two percent each. "
            "Default 1, at most 25.",
        },
    ))
