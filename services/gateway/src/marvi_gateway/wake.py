"""What the wake word is doing, for anyone who wants to know.

The gate had no surface at all. There was no way to see that the model had
loaded, no way to change the threshold without editing an environment
variable, and nothing at all when it fired — so a gate that was silently not
running looked exactly like a gate that was running and never triggered. Both
appear as Marvi ignoring you.

That distinction is the whole point of this module. `armed` says the model is
loaded and Marvi is listening for her name; `heard_at` says she has actually
recognised it, and when.

The state is in memory on purpose. A detection matters for the few seconds
after it happens — long enough for the orb to acknowledge it — and a record of
every time somebody said "Marvi" is a log of when people were in the room,
which is not a thing to keep.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .logs import get_logger

log = get_logger("wake")

#: Mirrors the Agent's own defaults. Duplicated rather than imported because
#: the Agent runs in a different Python environment; the test below fails if
#: the two drift.
DEFAULT_THRESHOLD = 0.5

#: How long a detection stays "recent" for the UI. Long enough to be seen,
#: short enough that it does not still be claiming she was called a minute ago.
RECENT_SECONDS = 6.0

_heard_at: float | None = None
_confidence = 0.0


def model_path() -> Path:
    """Where the wake word model is, configured or shipped.

    The shipped one lives beside the Agent's source rather than in the state
    directory: it is part of the build, not something the user installs.
    """
    configured = os.environ.get("MARVI_WAKE_MODEL", "").strip()
    if configured:
        return Path(configured)
    # Relative to this file rather than to an install-root variable: the model
    # ships beside the Agent's source, and that relationship holds in a
    # checkout and in an installation alike. MARVI_INSTALL_ROOT is a test
    # isolation knob and pointing at it here found nothing.
    #   .../services/gateway/src/marvi_gateway/wake.py -> .../services
    services = Path(__file__).resolve().parents[3]
    return services / "agent" / "wakeword" / "marvi.onnx"


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    return default if not raw else raw in ("1", "true", "yes", "on")


def _number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def heard(confidence: float = 0.0) -> None:
    """Record that the wake word just fired."""
    global _heard_at, _confidence
    _heard_at = time.time()
    _confidence = confidence


def forget() -> None:
    """Drop the last detection. For tests, and for turning the gate off."""
    global _heard_at, _confidence
    _heard_at = None
    _confidence = 0.0


#: A heartbeat older than this means the listener died rather than stopped.
#: Three times its write interval, so one slow write is not a death.
LISTENER_STALE_SECONDS = 15.0

#: Mirrors `marvi_agent.wake_autostart`. Duplicated because the Agent runs in a
#: different Python environment and this process cannot import it; the test
#: below fails if the two drift.
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "MarviWakeWord"


def listener_state_path() -> Path:
    """Where the standalone listener writes that it is alive."""
    from .paths import root

    return root() / "state" / "wake.json"


def registered() -> str:
    """The login command, or empty.

    Read live rather than cached: the user can turn this off from anywhere,
    including outside Marvi, and a cached "on" would be a lie that survives.
    """
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
        return str(value)
    except (FileNotFoundError, OSError, ImportError):
        return ""


def listener() -> dict[str, Any]:
    """What the always-on listener is doing, if anything.

    This is the distinction the status bar exists to make. "Registered" means
    it will start at login. "Running" means it is listening *now*. They come
    apart in the case that matters -- registered but crashed -- and that case
    used to be invisible, which is how a wake word that had not run for days
    looked exactly like one nobody had said the word to.
    """
    command = registered()
    state: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        state = json.loads(listener_state_path().read_text(encoding="utf-8"))

    beat = state.get("heartbeat")
    timed = isinstance(beat, int | float)
    silent_for = (time.time() - float(beat)) if timed else None
    fresh = timed and silent_for is not None and silent_for <= LISTENER_STALE_SECONDS
    heard_at = state.get("heard_at")
    return {
        "autostart": bool(command),
        "command": command,
        "running": bool(state.get("running")) and fresh,
        # How long since it last said anything, or None when it has never run.
        #
        # "Registered but not running" was reported as one thing and it is two.
        # A listener registered a second ago has not started yet; one whose
        # last heartbeat was thirty hours back has died, and the status bar
        # said STARTING for both -- so a wake word that had been dead since the
        # previous morning looked like one that was still warming up.
        "silent_for": None if silent_for is None else round(silent_for, 1),
        "ever_ran": timed,
        "pid": state.get("pid"),
        "started_at": state.get("started_at"),
        "heartbeat": beat,
        "heard_at": heard_at,
        "confidence": state.get("confidence", 0.0),
        "error": state.get("error", ""),
    }


def status() -> dict[str, Any]:
    path = model_path()
    enabled = _flag("MARVI_WAKE_WORD", True)
    present = path.is_file()
    live = listener()
    # The standalone listener does not post detections -- it may fire while the
    # Gateway is not even running, which is the whole point of it -- so its file
    # is the more recent truth whenever it has one.
    last = _heard_at
    if isinstance(live.get("heard_at"), int | float):
        last = max(last or 0.0, float(live["heard_at"]))
    age = None if last is None else time.time() - last
    return {
        "listener": live,
        "enabled": enabled,
        "model": str(path),
        "model_present": present,
        # Armed means both: switched on *and* the model is actually there. A
        # missing model leaves Marvi answering every turn rather than deaf, so
        # "enabled but not armed" is a real and reportable state.
        "armed": enabled and present,
        "threshold": _number("MARVI_WAKE_THRESHOLD", DEFAULT_THRESHOLD),
        "heard_at": last,
        "heard_seconds_ago": age,
        "recently_heard": age is not None and age <= RECENT_SECONDS,
        "confidence": _confidence,
        "setting": "MARVI_WAKE_WORD",
        "threshold_setting": "MARVI_WAKE_THRESHOLD",
        "device": os.environ.get(DEVICE_SETTING, ""),
        "device_setting": DEVICE_SETTING,
        "devices": microphones(),
    }


#: Which microphone the standalone listener opens. Empty means the system
#: default, which is what it always used -- and on a machine with a webcam, a
#: headset and a speakerphone that is frequently the wrong one, with no way to
#: say so.
DEVICE_SETTING = "MARVI_WAKE_DEVICE"


def microphones() -> list[dict[str, Any]]:
    """Input devices for the picker.

    Enumerated here with PortAudio rather than in the browser: the listener is
    a separate Python process using the same library, and `navigator.
    mediaDevices` lists what Chromium can open, under different names. A picker
    built from the wrong list offers microphones the thing doing the listening
    cannot open.

    This used to ask the Agent, by importing `marvi_agent.wake_daemon`. That
    failed in the running Gateway with "No module named 'marvi_agent'" -- twice
    a second for as long as the settings page was open, with an empty picker to
    show for it. The two services are separate uv projects and a cross-project
    import is only ever accidentally true. Duplicated instead, the way the
    registry constants above are, with a test pinning the two together.

    Two Windows quirks make the raw list unusable: the same microphone appears
    once per host API, and MME truncates names to 31 characters, so the
    duplicates are not even equal. A name that is a prefix of a longer one is
    dropped in favour of the longer.

    Never raises. An empty picker is a worse settings page; a failing one is no
    settings page.
    """
    try:
        import sounddevice
    except Exception as exc:  # pragma: no cover - depends on the install
        _say_once("audio", f"cannot list microphones: {exc}")
        return []
    try:
        devices = sounddevice.query_devices()
        default_name = str(sounddevice.query_devices(kind="input").get("name", "")).strip()
    except Exception as exc:  # pragma: no cover - depends on the machine
        _say_once("audio", f"cannot list microphones: {exc}")
        return []

    _say_once("audio", "")
    names: list[str] = []
    for device in devices:
        if int(device.get("max_input_channels", 0)) < 1:
            continue
        name = str(device.get("name", "")).strip()
        if name and name not in names:
            names.append(name)

    kept = [
        name
        for name in names
        if not any(other != name and other.startswith(name) for other in names)
    ]
    return [
        {
            # Handed to PortAudio verbatim: it matches on substrings, and a
            # tidied name may no longer match anything.
            "name": name,
            # What a person reads. Bluetooth headsets arrive with a newline and
            # a driver path in the middle of the name.
            "label": " ".join(name.split())[:64],
            "default": bool(name == default_name or (default_name and name.startswith(default_name))),
        }
        for name in kept
    ]


#: The last message announced per topic, so a warning is written when something
#: changes rather than every time the settings page polls.
_said: dict[str, str] = {}


def _say_once(topic: str, message: str) -> None:
    if _said.get(topic) == message:
        return
    _said[topic] = message
    if message:
        log.warning("%s", message)
