from __future__ import annotations

import base64
import contextlib
import json
import os
import sys
import sysconfig
from pathlib import Path


def _root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "Marvi-OS" / "models" / "tts" / "cutetts-distill"


def _send(event: str, **values: object) -> None:
    sys.__stdout__.write(json.dumps({"event": event, **values}) + "\n")
    sys.__stdout__.flush()


def _cloned(engine: str, voice: str) -> Path | None:
    """A voice recorded for this engine, if that is what was asked for.

    Cloned voices live beside the models rather than inside them, so a model
    reinstall does not take somebody's recordings with it. Checked before the
    bundled names because a clone can only ever be an addition -- the built-in
    identifiers are fixed and known.
    """
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    found = base / "Marvi-OS" / "voices" / engine / f"{voice}.wav"
    return found if found.is_file() else None


def _reference_voice(voice: str) -> Path:
    """Resolve the one voice shipped by the pinned upstream package.

    CuteTTS is a voice-cloning model with no voice bank at all: the one
    catalog entry is upstream's demo recording, and every other voice is one
    somebody recorded. See the Gateway's `cloning` module.

    Its web demo ships a reference recording
    and uses that recording for warmup, but Marvi previously advertised a
    made-up "Cute Default" and called plain TTS mode without any reference.
    That made the picker and the sound disagree. Keep the protocol explicit:
    the catalog voice maps to the exact upstream-bundled recording.
    """

    if clone := _cloned("cutetts-distill", voice):
        return clone
    if voice != "cute-reference":
        raise ValueError(f"unknown CuteTTS voice: {voice}")
    path = (
        Path(sysconfig.get_path("data")) / "share" / "cutetts" / "default_reference.wav"
    )
    if not path.is_file():
        raise FileNotFoundError(f"CuteTTS reference voice is missing: {path}")
    return path


def main() -> None:
    # Reserve the real stdout for the machine protocol. Imports and upstream
    # progress belong on stderr; `_send` deliberately retains `sys.__stdout__`.
    sys.stdout = sys.stderr
    try:
        with contextlib.redirect_stdout(sys.stderr):
            import numpy as np
            import torch
            from cutetts import CuteTTS
            from cutetts.modeling.sampling import set_sampler_compile_mode

            # Native Windows has no supported Triton path for this upstream.
            # The measured eager sampler is both stable and comfortably faster
            # than realtime on Marvi's target RTX 3060.
            torch._dynamo.config.suppress_errors = True
            model = CuteTTS.from_pretrained(_root(), device="cuda")
            set_sampler_compile_mode("eager")
            reference = _reference_voice("cute-reference")
            list(
                model.generate_stream(
                    "Marvi is ready.",
                    mode="voice_clone",
                    reference_audio=reference,
                    diffusion_steps=4,
                    show_progress=False,
                )
            )
        _send("ready", sample_rate=int(model.sample_rate))
    except Exception as exc:  # noqa: BLE001 - process boundary must report upstream failures
        _send("error", error=f"CuteTTS failed to load: {exc}")
        return

    for line in sys.stdin:
        try:
            request = json.loads(line)
            reference = _reference_voice(str(request.get("voice") or ""))
            with contextlib.redirect_stdout(sys.stderr):
                chunks = model.generate_stream(
                    str(request.get("text") or ""),
                    mode="voice_clone",
                    reference_audio=reference,
                    diffusion_steps=4,
                    show_progress=False,
                )
                for chunk in chunks:
                    samples = np.asarray(chunk.waveform, dtype=np.float32).reshape(-1)
                    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes()
                    _send("chunk", pcm=base64.b64encode(pcm).decode("ascii"))
            _send("done")
        except Exception as exc:  # noqa: BLE001 - keep the host alive for the next request
            _send("error", error=str(exc))


if __name__ == "__main__":
    main()
