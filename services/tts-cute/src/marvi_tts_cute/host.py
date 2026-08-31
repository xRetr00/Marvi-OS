from __future__ import annotations

import base64
import contextlib
import json
import os
import sys
from pathlib import Path

# Reserve the real stdout for the machine protocol. Upstream progress/logging
# goes to stderr, including imports outside the explicit redirect blocks.
sys.stdout = sys.stderr


def _root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "Marvi-OS" / "models" / "tts" / "cutetts-distill"


def _send(event: str, **values: object) -> None:
    sys.__stdout__.write(json.dumps({"event": event, **values}) + "\n")
    sys.__stdout__.flush()


def main() -> None:
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
            list(
                model.generate_stream(
                    "Marvi is ready.", diffusion_steps=4, show_progress=False
                )
            )
        _send("ready", sample_rate=int(model.sample_rate))
    except Exception as exc:  # noqa: BLE001 - process boundary must report upstream failures
        _send("error", error=f"CuteTTS failed to load: {exc}")
        return

    for line in sys.stdin:
        try:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                chunks = model.generate_stream(
                    str(request.get("text") or ""),
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
