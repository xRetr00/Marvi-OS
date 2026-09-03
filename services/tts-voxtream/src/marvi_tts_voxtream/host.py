from __future__ import annotations

import base64
import contextlib
import json
import os
import sys
from pathlib import Path

sys.stdout = sys.stderr


def _root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "Marvi-OS" / "models" / "tts" / "voxtream2"


#: Config the checkpoint ships with, and the one setting Marvi overrides.
#:
#: `prepare_prompt` runs inside *every* `generate_stream` call: it loads the
#: prompt WAV, encodes it through Mimi, and runs the ReDimNet speaker encoder
#: over it to build the voice embedding. None of that depends on the text being
#: spoken and none of it changes between utterances -- the prompt for a given
#: voice is a fixed file on disk -- so with `cache_prompt: false` it is the
#: same work, from scratch, on every reply.
#:
#: What that costs shows up in the voice log as speech that cannot keep up with
#: itself:
#:
#:     tts: 10.5s of audio in 13.1s (0.80x real time)  <- below real time
#:     tts:  3.3s of audio in  6.6s (0.50x real time)  <- below real time
#:     tts:  2.4s of audio in  5.5s (0.44x real time)  <- below real time
#:
#: Below one is not a number, it is the sound of Marvi talking, stopping, and
#: continuing: the player runs out of audio while the model is still making it.
#:
#: Upstream's own cache writes `<prompt>.prompt.npy` beside the WAV and skips
#: straight to the tensors. It is keyed on the file name alone, which is safe
#: here only because the two settings that would change the result --
#: `enhance_prompt` and `apply_vad` -- are false in this config and Marvi never
#: passes them; if either is ever turned on, the cached files have to go.
TUNING = {"cache_prompt": True}


def _settings(source: Path) -> dict:
    return {
        **json.loads((source / "configs" / "generator.json").read_text("utf-8")),
        **TUNING,
    }


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


def main() -> None:
    try:
        # Never compile. There is nothing here that can.
        #
        # `compile=False` is already passed to `SpeechGenerator`, but that is
        # VoXtream's own switch and it does not reach the Mimi codec underneath:
        # moshi decorates its gating, rope and transformer paths with
        # `torch_compile_lazy`, which compiles on first call unless
        # `NO_TORCH_COMPILE` is set. The Kyutai recogniser sets it. This did not,
        # and one afternoon of agent.log is 2,840 lines out of 3,648 -- 78% of
        # the file -- of this:
        #
        #     torch/_dynamo/convert_frame.py:1125] BackendCompilerFailed:
        #     backend='inductor' raised: RuntimeError: Cannot find a working
        #     triton installation.
        #
        # forty separate times. There is no triton on Windows, so inductor
        # cannot succeed here, ever. `suppress_errors` catches each failure and
        # falls back to eager, which is why this was a warning rather than a
        # crash -- but dynamo re-traces and re-attempts on every new input
        # shape, and text of a different length is a different shape, so the
        # cost recurs instead of being paid once at load.
        #
        # `NO_TORCH_COMPILE` is moshi's switch; `TORCHDYNAMO_DISABLE` covers
        # VoXtream's own code and the speaker encoder, which moshi's does not.
        os.environ.setdefault("NO_TORCH_COMPILE", "1")
        os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")
        os.environ.setdefault("HF_HOME", str(_root() / "huggingface"))
        source = _root() / "source"
        with contextlib.redirect_stdout(sys.stderr):
            import numpy as np
            import torch
            import torch._dynamo
            from voxtream.config import SpeechGeneratorConfig
            from voxtream.generator import SpeechGenerator

            torch._dynamo.config.suppress_errors = True
            config = SpeechGeneratorConfig(**_settings(source))
            speaking_rate = json.loads(
                (source / "configs" / "speaking_rate.json").read_text("utf-8")
            )
            generator = SpeechGenerator(config, speaking_rate, compile=False)
            list(
                generator.generate_stream(
                    prompt_audio_path=source
                    / "assets"
                    / "audio"
                    / "english_female.wav",
                    text="Marvi is ready.",
                )
            )
        _send("ready", sample_rate=int(config.mimi_sr))
    except Exception as exc:  # noqa: BLE001 - process boundary must report upstream failures
        _send("error", error=f"VoXtream2 failed to load: {exc}")
        return

    for line in sys.stdin:
        try:
            request = json.loads(line)
            asked = str(request.get("voice") or "english-female")
            # A recorded voice wins over a bundled one. The bundled names are
            # fixed, so a clone can only ever be an addition, never a shadow.
            prompt = _cloned("voxtream2", asked) or (
                source / "assets" / "audio" / f"{asked.replace('-', '_')}.wav"
            )
            with contextlib.redirect_stdout(sys.stderr):
                for frame, _compute_seconds in generator.generate_stream(
                    prompt_audio_path=prompt,
                    text=str(request.get("text") or ""),
                ):
                    samples = np.asarray(frame, dtype=np.float32).reshape(-1)
                    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes()
                    _send("chunk", pcm=base64.b64encode(pcm).decode("ascii"))
            _send("done")
        except Exception as exc:  # noqa: BLE001 - keep the host alive for the next request
            _send("error", error=str(exc))


if __name__ == "__main__":
    main()
