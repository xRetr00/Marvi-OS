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

import base64
import ctypes
import io
import time
from typing import Any

from .untrusted import wrap_external

#: Plenty for "what did I just copy"; a whole log pasted into a turn is not.
MAX_CLIPBOARD_CHARS = 20_000

CF_UNICODETEXT = 13
CF_DIB = 8
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


def read_image() -> bytes | None:
    """A copied picture as PNG bytes, or None when the clipboard holds none.

    Windows hands out `CF_DIB`: a bitmap *without* the 14-byte file header
    every decoder expects, because the format predates anybody needing to save
    one. Putting the header back is the whole conversion; Pillow is already a
    dependency for the vision pipeline and does the rest.
    """
    user32, kernel32 = _win32()
    if not user32.IsClipboardFormatAvailable(CF_DIB):
        return None
    _open_clipboard(user32)
    try:
        handle = user32.GetClipboardData(CF_DIB)
        if not handle:
            return None
        size = kernel32.GlobalSize(ctypes.c_void_p(handle))
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            dib = ctypes.string_at(pointer, size)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()

    header_size = int.from_bytes(dib[:4], "little")
    # 40-byte BITMAPINFOHEADER and 124-byte V5 both start with their own size;
    # the pixel data begins after the header and any colour table.
    colours = int.from_bytes(dib[32:36], "little") if header_size >= 36 else 0
    offset = 14 + header_size + colours * 4
    bmp = (
        b"BM"
        + (14 + len(dib)).to_bytes(4, "little")
        + bytes(4)  # two reserved words, zero
        + offset.to_bytes(4, "little")
        + dib
    )

    from PIL import Image

    with Image.open(io.BytesIO(bmp)) as image:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def press(virtual_key: int) -> None:
    user32, _ = _win32()
    user32.keybd_event(virtual_key, 0, 0, 0)
    user32.keybd_event(virtual_key, 0, KEYEVENTF_KEYUP, 0)


# -- the speaker's actual level -----------------------------------------------
#
# The media keys move the volume by two percent a press and cannot say where it
# started, so "set it to thirty" and "how loud is it?" are both unanswerable
# with them. Core Audio answers both, and it is reachable from `ctypes` without
# a package: three COM interfaces, called by vtable index because there is no
# type library to import. pycaw would be the dependency version of these forty
# lines, and it brings comtypes with it.

_CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_IID_IAudioEndpointVolume = "{5CDF2C82-841E-4546-9722-0CF74078229A}"
#: `eRender`, `eMultimedia`: the speakers, as an app that plays media sees them.
_RENDER, _MULTIMEDIA = 0, 1


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(text: str) -> _GUID:
    value = _GUID()
    if ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(value)) != 0:
        raise DeskUnavailableError(f"bad GUID {text}")
    return value


_VOIDPP = ctypes.POINTER(ctypes.c_void_p)


def _method(pointer: ctypes.c_void_p, index: int, *argtypes: Any) -> Any:
    """One COM method, by its slot in the vtable.

    The argument types are given rather than inferred: `byref(x)` is a
    `CArgObject`, which ctypes will not accept as an argument *type*, so
    inferring them from the values fails on every call that returns something.
    """
    vtable = ctypes.cast(pointer, ctypes.POINTER(_VOIDPP))
    prototype = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)
    return prototype(vtable[0][index])


def _release(pointer: ctypes.c_void_p) -> None:
    _method(pointer, 2)(pointer)


class _EndpointVolume:
    """The default playback device's volume control, released on exit."""

    def __enter__(self) -> _EndpointVolume:
        try:
            ole32 = ctypes.windll.ole32
        except AttributeError as exc:
            raise DeskUnavailableError("volume control is Windows-only") from exc
        ole32.CoInitialize(None)
        enumerator = ctypes.c_void_p()
        if ole32.CoCreateInstance(
            ctypes.byref(_guid(_CLSID_MMDeviceEnumerator)),
            None,
            1,  # CLSCTX_INPROC_SERVER
            ctypes.byref(_guid(_IID_IMMDeviceEnumerator)),
            ctypes.byref(enumerator),
        ) != 0:
            raise DeskUnavailableError("Windows would not open the audio device list")
        device = ctypes.c_void_p()
        # IMMDeviceEnumerator::GetDefaultAudioEndpoint is slot 4 (3 IUnknown first).
        found = _method(enumerator, 4, ctypes.c_int, ctypes.c_int, _VOIDPP)(
            enumerator, _RENDER, _MULTIMEDIA, ctypes.byref(device)
        )
        if found != 0:
            _release(enumerator)
            raise DeskUnavailableError("there is no default playback device")
        volume = ctypes.c_void_p()
        # IMMDevice::Activate is slot 3.
        activated = _method(
            device, 3, ctypes.POINTER(_GUID), ctypes.c_uint32, ctypes.c_void_p, _VOIDPP
        )(
            device,
            ctypes.byref(_guid(_IID_IAudioEndpointVolume)),
            1,  # CLSCTX_INPROC_SERVER
            None,
            ctypes.byref(volume),
        )
        _release(device)
        _release(enumerator)
        if activated != 0:
            raise DeskUnavailableError("Windows would not hand over the volume control")
        self._volume = volume
        return self

    def __exit__(self, *_exception: Any) -> None:
        _release(self._volume)

    def level(self) -> int:
        """Where the slider is, 0-100."""
        scalar = ctypes.c_float()
        # IAudioEndpointVolume::GetMasterVolumeLevelScalar is slot 9.
        if _method(self._volume, 9, ctypes.POINTER(ctypes.c_float))(
            self._volume, ctypes.byref(scalar)
        ) != 0:
            raise DeskUnavailableError("could not read the volume")
        return round(scalar.value * 100)

    def set_level(self, percent: int) -> int:
        wanted = max(0, min(100, int(percent)))
        # SetMasterVolumeLevelScalar is slot 7; the last argument is an event
        # GUID for whoever else is listening, and None means "no particular
        # event", which is what a person moving the slider produces.
        if _method(self._volume, 7, ctypes.c_float, ctypes.c_void_p)(
            self._volume, wanted / 100, None
        ) != 0:
            raise DeskUnavailableError("could not set the volume")
        return wanted

    def muted(self) -> bool:
        state = ctypes.c_int()
        # GetMute is slot 15.
        if _method(self._volume, 15, ctypes.POINTER(ctypes.c_int))(
            self._volume, ctypes.byref(state)
        ) != 0:
            raise DeskUnavailableError("could not read the mute switch")
        return bool(state.value)


def volume_now() -> dict[str, Any]:
    with _EndpointVolume() as endpoint:
        return {"level": endpoint.level(), "muted": endpoint.muted()}


def set_volume(percent: int) -> dict[str, Any]:
    with _EndpointVolume() as endpoint:
        return {"level": endpoint.set_level(percent), "muted": endpoint.muted()}


#: What the vision model is asked about a copied picture, when nobody said.
CLIPBOARD_IMAGE_QUESTION = "What is in this image? Answer in two or three sentences."


def _describe_clipboard_image(client: Any) -> dict[str, Any]:
    """The picture on the clipboard, as words.

    Same trade as `read_screen`: the answer comes back, not the image. The
    voice model usually cannot take an image at all, and a screenshot in a
    conversation's context stays there for the rest of it.
    """
    from . import auxiliary, prompts

    try:
        png = read_image()
    except DeskUnavailableError as exc:
        return {"error": str(exc)}
    if png is None:
        return {"empty": True, "note": "the clipboard holds no text and no picture"}
    if client is None:
        return {
            "empty": False,
            "error": "There is a picture on the clipboard, but no model is set to read images. "
            "Set the Vision role in Settings > Models.",
        }
    try:
        completion = client.call_with_fallback(
            [
                {"role": "system", "content": prompts.text("screen-reading")},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": CLIPBOARD_IMAGE_QUESTION},
                        {
                            "type": "image",
                            "media_type": "image/png",
                            "data": base64.b64encode(png).decode("ascii"),
                        },
                    ],
                },
            ],
            job="vision",
            max_tokens=500,
            temperature=0.2,
            **auxiliary.fallback_overrides("vision"),
        )
    except Exception as exc:
        return {"error": f"the copied picture could not be read: {exc}"}
    answer = (getattr(completion, "text", "") or "").strip()
    # A picture is external content like any other: it can contain writing that
    # is addressed to whoever reads it.
    return {
        "kind": "image",
        "bytes": len(png),
        "text": wrap_external("clipboard-image", answer or "Nothing legible.").model_dump(),
    }


def register_desk_tools(registry: Any, client: Any = None) -> None:
    from .tools import ToolSpec

    def clipboard_read() -> dict[str, Any]:
        try:
            text = read_text()
        except DeskUnavailableError as exc:
            return {"error": str(exc)}
        if not text:
            return _describe_clipboard_image(client)
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

    def media_control(action: str, steps: int = 1, level: int = -1) -> dict[str, Any]:
        wanted = action.strip().lower()
        # "Set it to thirty" is a different instruction from "turn it down
        # twice", and only one of them can be said with the media keys.
        if wanted in ("volume_set", "set_volume") or (level >= 0 and wanted.startswith("volume")):
            if level < 0:
                return {"error": "volume_set needs level, 0 to 100"}
            try:
                return {"volume": set_volume(level)["level"]}
            except DeskUnavailableError as exc:
                return {"error": str(exc)}
        key = MEDIA_KEYS.get(wanted)
        if key is None:
            return {
                "error": f"unknown action {action!r}; use one of "
                f"{', '.join([*MEDIA_KEYS, 'volume_set'])}"
            }
        # Only the volume keys repeat; pressing "next" five times is a different request.
        count = max(1, min(int(steps), MAX_STEPS)) if wanted.startswith("volume") else 1
        try:
            for _ in range(count):
                press(key)
        except DeskUnavailableError as exc:
            return {"error": str(exc)}
        return {"pressed": wanted, "times": count}

    def media_status() -> dict[str, Any]:
        try:
            return volume_now()
        except DeskUnavailableError as exc:
            return {"error": str(exc)}

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
        optional={"steps": int, "level": int},
        sensitive=False,
        handler=media_control,
        describes={
            "action": "One of: " + ", ".join([*MEDIA_KEYS, "volume_set"]) + ".",
            "steps": "For volume_up and volume_down only: how many presses, two percent each. "
            "Default 1, at most 25.",
            "level": "For volume_set: the level to set, 0 to 100. Read media_status first when "
            "the user asks for a change relative to now.",
        },
    ))
    registry.register(ToolSpec(
        name="media_status",
        description="How loud the speakers are set, and whether they are muted.",
        arguments={},
        sensitive=False,
        handler=media_status,
    ))
