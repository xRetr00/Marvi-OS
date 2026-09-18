"""Recording what the speakers are playing, and what the microphone hears.

A meeting has two sides and Marvi is on one of them. The microphone gets the
owner; everyone else arrives as *playback* -- Teams rendering their voices to
the speakers -- and there is no microphone in the world that hears that
cleanly. WASAPI has an answer, `AUDCLNT_STREAMFLAGS_LOOPBACK`: the same audio
the device is rendering, handed back as a capture stream.

## Why this is ctypes and not the audio library already installed

`sounddevice` is a declared dependency and captures a microphone in four lines.
It cannot do loopback here: the option exists in its API, but the PortAudio
build that ships with it (V19.7.0-devel, checked on this machine) does not
carry the flag, and `WasapiSettings(loopback=True)` is a `TypeError` rather
than a recording. Shipping a different PortAudio to get one flag is a binary to
vendor, audit and keep current.

So the OS interface directly, the same way `desk.py` reaches the volume
control: three COM interfaces called by vtable slot, no package. Both ends use
the same path -- the microphone is the same code with `eCapture` and no
loopback flag -- because one mechanism with a parameter is easier to trust than
two that have to agree.

## The format

`GetMixFormat` is asked rather than told: it returns what the device is
actually rendering, and a loopback stream opened with the device's own mix
format never has to negotiate. That is float32, usually 48 kHz stereo, and the
recogniser wants 16 kHz mono 16-bit -- so this converts, in the capture thread,
and hands on PCM that is ready to transcribe.

Downsampling is an average over each group of input samples rather than picking
one of them. Both are cheap; only one of them avoids aliasing a voice into a
buzz, and speech recognition notices.
"""

from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from typing import Any

from .logs import get_logger

log = get_logger("gateway")

#: What the recogniser wants, whatever the device is doing.
TARGET_RATE = 16_000

_CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_IID_IAudioClient = "{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}"
_IID_IAudioCaptureClient = "{C8ADBD64-E71E-48A0-A4DE-185C395CD317}"

#: `eRender` is the speakers, `eCapture` the microphone; `eMultimedia` is the
#: role an app that plays or records media asks for.
_RENDER, _CAPTURE, _MULTIMEDIA = 0, 1, 1

_SHARED = 0
_LOOPBACK = 0x00020000
#: 200 ms of buffer, in 100-nanosecond units. Enough that a busy moment does
#: not drop audio, small enough that stopping is prompt.
_BUFFER = 2_000_000

_WAVE_FORMAT_IEEE_FLOAT = 3
_WAVE_FORMAT_EXTENSIBLE = 0xFFFE
#: `AUDCLNT_BUFFERFLAGS_SILENT`: the buffer is not zeroed, it is *declared*
#: silent, and reading it as audio gives whatever was in the memory before.
_SILENT = 0x2


class CaptureUnavailableError(RuntimeError):
    """This machine will not give us the stream, and said why."""


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _WaveFormatEx(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


def _guid(text: str) -> _GUID:
    value = _GUID()
    if ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(value)) != 0:
        raise CaptureUnavailableError(f"bad GUID {text}")
    return value


_VOIDPP = ctypes.POINTER(ctypes.c_void_p)


def _method(pointer: ctypes.c_void_p, index: int, *argtypes: Any) -> Any:
    """One COM method, by its slot in the vtable. See `desk.py` for the why."""
    vtable = ctypes.cast(pointer, ctypes.POINTER(_VOIDPP))
    prototype = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)
    return prototype(vtable[0][index])


def _release(pointer: ctypes.c_void_p) -> None:
    if pointer:
        _method(pointer, 2)(pointer)


def _mono16k(raw: bytes, channels: int, rate: int, floats: bool) -> bytes:
    """A device buffer as 16 kHz mono signed 16-bit, ready for the recogniser."""
    import numpy

    if floats:
        samples = numpy.frombuffer(raw, dtype=numpy.float32)
    else:
        samples = numpy.frombuffer(raw, dtype=numpy.int16).astype(numpy.float32) / 32768.0
    if channels > 1:
        usable = (samples.size // channels) * channels
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)
    if rate != TARGET_RATE and samples.size:
        # An average over each group rather than every Nth sample: picking one
        # aliases a voice into a buzz, and the recogniser hears the difference.
        step = rate / TARGET_RATE
        wanted = int(samples.size / step)
        if wanted <= 0:
            return b""
        edges = (numpy.arange(wanted + 1) * step).astype(numpy.int64)
        totals = numpy.concatenate(([0.0], numpy.cumsum(samples, dtype=numpy.float64)))
        counts = numpy.maximum(edges[1:] - edges[:-1], 1)
        samples = ((totals[edges[1:]] - totals[edges[:-1]]) / counts).astype(numpy.float32)
    clipped = numpy.clip(samples, -1.0, 1.0) * 32767.0
    return clipped.astype(numpy.int16).tobytes()


class Capture:
    """One endpoint, recorded in a thread until it is stopped.

    `speakers=True` is the loopback stream -- everything the machine is
    playing. `speakers=False` is the microphone. Both hand `on_pcm` 16 kHz
    mono 16-bit, in whatever sized pieces the device delivers.
    """

    def __init__(self, speakers: bool, on_pcm: Callable[[bytes], None]) -> None:
        self.speakers = speakers
        self._on_pcm = on_pcm
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        #: Set by the thread if it could not start, so `start()` can raise it
        #: on the caller's thread where somebody will see it.
        self._failed: Exception | None = None
        self._running = threading.Event()
        #: Loudest sample seen, 0-32767. The recording indicator reads it, and
        #: "recording but silent" is a thing people need to be able to notice.
        self.peak = 0
        self.frames = 0

    def start(self, wait: float = 5.0) -> None:
        self._thread = threading.Thread(target=self._run, name="marvi-capture", daemon=True)
        self._thread.start()
        if not self._running.wait(timeout=wait) and self._failed is None:
            self.stop()
            raise CaptureUnavailableError("the audio device did not start in time")
        if self._failed is not None:
            raise self._failed

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        enumerator = device = client = capture = ctypes.c_void_p()
        ole32 = None
        try:
            ole32 = ctypes.windll.ole32
            # `COINIT_MULTITHREADED`: this is a worker thread with no message
            # pump, and an apartment-threaded one would deadlock on release.
            ole32.CoInitializeEx(None, 0x0)
            enumerator = ctypes.c_void_p()
            if ole32.CoCreateInstance(
                ctypes.byref(_guid(_CLSID_MMDeviceEnumerator)), None, 1,
                ctypes.byref(_guid(_IID_IMMDeviceEnumerator)), ctypes.byref(enumerator),
            ) != 0:
                raise CaptureUnavailableError("Windows would not open the audio device list")

            device = ctypes.c_void_p()
            if _method(enumerator, 4, ctypes.c_int, ctypes.c_int, _VOIDPP)(
                enumerator, _RENDER if self.speakers else _CAPTURE, _MULTIMEDIA,
                ctypes.byref(device),
            ) != 0:
                raise CaptureUnavailableError(
                    "there is no default playback device" if self.speakers
                    else "there is no default microphone"
                )

            client = ctypes.c_void_p()
            if _method(
                device, 3, ctypes.POINTER(_GUID), ctypes.c_uint32, ctypes.c_void_p, _VOIDPP
            )(device, ctypes.byref(_guid(_IID_IAudioClient)), 1, None, ctypes.byref(client)) != 0:
                raise CaptureUnavailableError("Windows would not hand over the audio client")

            # Asked, not told: the device's own mix format always works, and a
            # loopback stream opened with it never has to negotiate.
            formats = ctypes.POINTER(_WaveFormatEx)()
            if _method(client, 8, ctypes.POINTER(ctypes.POINTER(_WaveFormatEx)))(
                client, ctypes.byref(formats)
            ) != 0:
                raise CaptureUnavailableError("Windows would not say what format the device is in")
            channels = int(formats.contents.nChannels)
            rate = int(formats.contents.nSamplesPerSec)
            bits = int(formats.contents.wBitsPerSample)
            tag = int(formats.contents.wFormatTag)
            block = int(formats.contents.nBlockAlign)
            # `EXTENSIBLE` hides the real tag in a GUID; at 32 bits it is float
            # in every mix format Windows produces, and the buffer proves it.
            floats = tag == _WAVE_FORMAT_IEEE_FLOAT or (tag == _WAVE_FORMAT_EXTENSIBLE and bits == 32)

            if _method(
                client, 3, ctypes.c_int, wintypes.DWORD, ctypes.c_longlong, ctypes.c_longlong,
                ctypes.POINTER(_WaveFormatEx), ctypes.c_void_p,
            )(
                client, _SHARED, _LOOPBACK if self.speakers else 0, _BUFFER, 0, formats, None,
            ) != 0:
                raise CaptureUnavailableError("Windows would not open the stream")

            capture = ctypes.c_void_p()
            if _method(client, 14, ctypes.POINTER(_GUID), _VOIDPP)(
                client, ctypes.byref(_guid(_IID_IAudioCaptureClient)), ctypes.byref(capture)
            ) != 0:
                raise CaptureUnavailableError("Windows would not hand over the capture client")

            if _method(client, 10)(client) != 0:
                raise CaptureUnavailableError("Windows would not start the stream")

            self._running.set()
            log.info("recording the %s", "speakers" if self.speakers else "microphone")
            self._pump(capture, channels, rate, block, floats)
            _method(client, 11)(client)
        except Exception as exc:  # reported on the caller's thread
            self._failed = exc if isinstance(exc, Exception) else CaptureUnavailableError(str(exc))
            self._running.set()
        finally:
            _release(capture)
            _release(client)
            _release(device)
            _release(enumerator)
            if ole32 is not None:
                ole32.CoUninitialize()

    def _pump(
        self, capture: ctypes.c_void_p, channels: int, rate: int, block: int, floats: bool
    ) -> None:
        """Drain the device until told to stop. Ten milliseconds at a time."""
        get_next = _method(capture, 5, ctypes.POINTER(wintypes.UINT))
        get_buffer = _method(
            capture, 3, ctypes.POINTER(ctypes.POINTER(ctypes.c_byte)),
            ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(ctypes.c_ulonglong),
        )
        release = _method(capture, 4, wintypes.UINT)
        while not self._stop.is_set():
            waiting = wintypes.UINT(0)
            if get_next(capture, ctypes.byref(waiting)) != 0:
                break
            if waiting.value == 0:
                time.sleep(0.01)
                continue
            data = ctypes.POINTER(ctypes.c_byte)()
            frames = wintypes.UINT(0)
            flags = wintypes.DWORD(0)
            if get_buffer(
                capture, ctypes.byref(data), ctypes.byref(frames), ctypes.byref(flags), None, None
            ) != 0:
                break
            try:
                if frames.value:
                    if flags.value & _SILENT:
                        # Declared silent, not zeroed. Reading it as audio
                        # gives whatever the memory held, which is a burst of
                        # noise the recogniser will happily hallucinate over.
                        chunk = b"\0" * (frames.value * 2 * TARGET_RATE // max(rate, 1) or 2)
                    else:
                        raw = ctypes.string_at(data, frames.value * block)
                        chunk = _mono16k(raw, channels, rate, floats)
                        self.peak = max(self.peak, _peak(chunk))
                    self.frames += frames.value
                    if chunk:
                        self._on_pcm(chunk)
            finally:
                release(capture, frames.value)


def _peak(pcm16: bytes) -> int:
    import numpy

    if not pcm16:
        return 0
    return int(abs(numpy.frombuffer(pcm16, dtype=numpy.int16).astype(numpy.int32)).max())


def available() -> tuple[bool, str]:
    """Whether both ends can be recorded here, and what is missing if not."""
    import os

    if os.name != "nt":
        return False, "recording the speakers needs WASAPI, which is Windows"
    try:
        import numpy  # noqa: F401
    except ImportError:
        return False, "numpy is not installed, and the conversion needs it"
    return True, ""
