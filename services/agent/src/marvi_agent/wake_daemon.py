"""Marvi answers to her name whether or not she is open.

The wake word used to live inside the voice session, which made it useless for
the thing a wake word is *for*. You had to open Marvi and press Join before she
could hear you -- and once you had pressed Join she was already listening, so
the gate only ever decided which of the turns you had already started counted.

This is the other design, and the one the name implies: a small process that
starts at login, holds the microphone, and does nothing but wait for the word.
It is not a gate on a running conversation. It is the Join button, pressed
hands-free:

    heard "Marvi" -> is the app running?
                     yes -> tell it to join
                     no  -> start it, and it joins as it comes up

Both branches are the same call. ``Marvi.exe --wake`` starts the app if it is
closed, and if it is already open Electron's single-instance lock delivers the
argument to the running copy instead of starting a second one. There is no
"is it running" check here because the operating system already answers that
question correctly, and a check of our own would race with the answer.

**What it costs when idle.** One 2-second window of 16 kHz mono audio scored
every half second: a few hundred kilobytes of buffer and a small ONNX model.
No network, no STT, no tokens. Nothing leaves the machine and nothing is
recorded -- the buffer is a ring that overwrites itself continuously, so the
only audio that exists anywhere is the two seconds currently being scored.

**Why it is not in the Agent.** The Agent needs a room, the room needs the
Gateway, and the Gateway needs the app to be open -- which is the state this
process exists to escape. It shares the Agent's environment because the model
and ``livekit-wakeword`` are already there, but it imports none of it.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("marvi.wake")

SAMPLE_RATE = 16_000
#: The model is stateless and wants about two seconds of speech. Shorter than
#: this and `predict` returns exactly 0.0 -- not "no wake word", but "I was not
#: given enough audio to have an opinion", which reads identically and is why
#: an earlier version looked like a model that never fired.
WINDOW_SECONDS = 2.0
#: How often the window is scored. Half the phrase length, so the word cannot
#: fall across a boundary and be missed by both halves.
HOP_SECONDS = 0.5
#: One "Marvi" is one join. Without this the word stays in the window for its
#: whole two seconds and fires four times.
DEBOUNCE_SECONDS = 4.0
#: Written this often so the UI can tell a listener that is running from one
#: that died. Comfortably inside the staleness window the Gateway applies.
HEARTBEAT_SECONDS = 5.0
DEFAULT_THRESHOLD = 0.5


def state_path() -> Path:
    """Where the listener says it is alive.

    A file rather than a port: this process starts before the Gateway and
    outlives it, so it cannot register anywhere. The Gateway reads it when
    somebody asks, which is the only time the answer matters.
    """
    configured = os.environ.get("MARVI_HOME", "").strip()
    if configured:
        root = Path(configured)
    else:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        root = Path(base) / "Marvi-OS"
    return root / "state" / "wake.json"


def model_path() -> Path:
    """The shipped model, or the one that was configured instead."""
    configured = os.environ.get("MARVI_WAKE_MODEL", "").strip()
    if configured:
        return Path(configured)
    # .../src/marvi_agent/wake_daemon.py -> .../services/agent
    return Path(__file__).resolve().parents[2] / "wakeword" / "marvi.onnx"


def app_command(app: str = "") -> list[str]:
    """How to reach Marvi, running or not.

    ``--wake`` rather than a bespoke IPC channel: it is the same argument in
    both cases, and Electron's single-instance lock decides which of the two
    things it means.

    The path is passed in rather than discovered. Whatever registers this
    listener at login already knows where the executable is, and an update that
    moves it rewrites the registration -- guessing from this process, whose own
    interpreter lives in a virtual environment several directories away, was
    wrong in every installed layout.
    """
    chosen = app.strip() or os.environ.get("MARVI_APP_COMMAND", "").strip()
    if not chosen:
        root = os.environ.get("MARVI_INSTALL_ROOT", "").strip()
        chosen = str(Path(root) / "Marvi.exe") if root else "Marvi.exe"
    return [chosen, "--wake"]


def write_state(**fields: object) -> None:
    """Never raises.

    A listener that is working must not stop because the file describing it
    could not be written.
    """
    with contextlib.suppress(Exception):
        path = state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pid": os.getpid(), **fields}), encoding="utf-8")


def join(confidence: float, app: str = "") -> None:
    """Press Join, hands-free."""
    command = app_command(app)
    log.info("wake word heard (%.2f); %s", confidence, " ".join(command))
    try:
        # Detached: this listener outlives any one run of the app, so it must
        # not become the parent of one. No window, because a console flashing
        # up at the sound of your own voice is its own kind of alarm.
        creation = 0
        if sys.platform == "win32":
            creation = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        subprocess.Popen(command, creationflags=creation, close_fds=True)
    except Exception as exc:  # noqa: BLE001 - a bad path must not kill the listener
        log.warning("could not start or signal the app: %s", exc)


def listen(threshold: float, app: str = "") -> int:
    import sounddevice
    from livekit.wakeword import WakeWordModel

    path = model_path()
    if not path.is_file():
        log.error("no wake word model at %s", path)
        write_state(running=False, error=f"no model at {path}")
        return 1

    model = WakeWordModel(models=[str(path)])
    window = int(SAMPLE_RATE * WINDOW_SECONDS)
    hop = int(SAMPLE_RATE * HOP_SECONDS)
    # int16, because that is what the model was trained on and what the
    # in-session detector feeds it. Handing it floats scores noise.
    buffer = np.zeros(window, dtype=np.int16)
    filled = 0
    last_fired = 0.0
    last_beat = 0.0
    started = time.time()
    log.info("listening for the wake word at %.2f (%s)", threshold, path)

    with sounddevice.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=hop
    ) as stream:
        while True:
            chunk, overflowed = stream.read(hop)
            if overflowed:
                # Dropped audio is a missed word, not a crash. Worth knowing
                # about when somebody reports she stopped answering.
                log.debug("input overflow; a hop of audio was dropped")
            buffer = np.roll(buffer, -hop)
            buffer[-hop:] = chunk[:, 0]
            filled = min(filled + hop, window)

            now = time.time()
            if now - last_beat >= HEARTBEAT_SECONDS:
                last_beat = now
                write_state(running=True, started_at=started, heartbeat=now, model=str(path))

            # Scoring a part-full buffer scores mostly silence, and the model
            # has no way to say so -- it returns a number either way.
            if filled < window or now - last_fired < DEBOUNCE_SECONDS:
                continue

            # A dict of model name to score; this build ships one model.
            score = max(model.predict(buffer).values(), default=0.0)
            if score < threshold:
                continue

            last_fired = now
            write_state(
                running=True,
                started_at=started,
                heartbeat=now,
                model=str(path),
                heard_at=now,
                confidence=score,
            )
            join(score, app)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Listen for the Marvi wake word.")
    parser.add_argument(
        "--threshold",
        type=float,
        default=float(os.environ.get("MARVI_WAKE_THRESHOLD") or DEFAULT_THRESHOLD),
    )
    parser.add_argument(
        "--app",
        default="",
        help="path to Marvi.exe; whatever registered this listener knows it",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return listen(args.threshold, args.app)
    except KeyboardInterrupt:
        return 0
    finally:
        write_state(running=False, stopped_at=time.time())


if __name__ == "__main__":
    raise SystemExit(main())
