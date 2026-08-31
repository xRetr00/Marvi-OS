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


def _send(event: str, **values: object) -> None:
    sys.__stdout__.write(json.dumps({"event": event, **values}) + "\n")
    sys.__stdout__.flush()


def main() -> None:
    try:
        os.environ.setdefault("HF_HOME", str(_root() / "huggingface"))
        source = _root() / "source"
        with contextlib.redirect_stdout(sys.stderr):
            import numpy as np
            import torch
            import torch._dynamo
            from voxtream.config import SpeechGeneratorConfig
            from voxtream.generator import SpeechGenerator

            torch._dynamo.config.suppress_errors = True
            config = SpeechGeneratorConfig(
                **json.loads((source / "configs" / "generator.json").read_text("utf-8"))
            )
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
            voice = str(request.get("voice") or "english-female").replace("-", "_")
            prompt = source / "assets" / "audio" / f"{voice}.wav"
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
