"""Kyutai STT in its own process, speaking newline-delimited JSON.

The same shape as the two TTS sidecars, and for the same reason: `moshi` pins a
torch that would replace the agent's CUDA build with a CPU one and take Kokoro
down with it. Only PCM and text cross this boundary.

## The protocol

One JSON object per line, both directions.

    -> {"op": "reset"}                       start a fresh utterance
    -> {"op": "feed", "pcm": "<base64>"}     exactly one 80 ms frame
    -> {"op": "flush"}                       push past the model's text delay
    <- {"event": "ready", "sample_rate": 24000, "heads": 4}
    <- {"event": "text", "text": " hello", "done": 0.03}
    <- {"event": "error", "error": "..."}

`done` is the pause probability from the chosen head -- the reason this
recogniser exists. It rides on every frame rather than being asked for,
because the caller needs it at the same rate it needs the text and a second
round trip per 80 ms would be absurd.

## Why one frame per message

Mimi consumes exactly 1,920 samples at a time and nothing else is a valid feed
size, so the boundary may as well be the model's own. At 12.5 frames a second
carrying 3.4 KB of base64 each, the pipe is not the expensive part; the 60 ms
of GPU work behind it is.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import sys
from pathlib import Path

#: Which pause head to read. 0 is 0.5 s, 1 is 1.0 s, 2 is 2.0 s, 3 is 3.0 s.
#: Two is what Kyutai ship in Unmute and what measured fewest premature
#: endings here. The agent passes its own value; this is the fallback.
VAD_INDEX = 2


def _root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "Marvi-OS" / "models" / "stt" / "kyutai-stt-1b-candle"


def _send(event: str, **values: object) -> None:
    sys.__stdout__.write(json.dumps({"event": event, **values}) + "\n")
    sys.__stdout__.flush()


def main() -> None:
    # The real stdout is the protocol. Upstream's progress bars and every
    # import that prints go to stderr.
    sys.stdout = sys.stderr
    os.environ.setdefault("NO_TORCH_COMPILE", "1")
    try:
        with contextlib.redirect_stdout(sys.stderr):
            import numpy as np
            import torch
            from moshi.models import LMGen, loaders

            root = _root()
            checkpoint = loaders.CheckpointInfo.from_hf_repo(
                "kyutai/stt-1b-en_fr-candle",
                config_path=root / "config.json",
                moshi_weights=root / "model.safetensors",
                mimi_weights=root / "mimi-pytorch-e351c8d8@125.safetensors",
                tokenizer=root / "tokenizer_en_fr_audio_8000.model",
            )
            device = "cuda" if torch.cuda.is_available() else "cpu"
            mimi = checkpoint.get_mimi(device=device)
            tokenizer = checkpoint.get_text_tokenizer()
            lm = checkpoint.get_moshi(device=device)
            gen = LMGen(lm, temp=0, temp_text=0, use_sampling=False)
            heads = len(getattr(lm, "extra_heads", ()) or ())
            frame = int(mimi.sample_rate / mimi.frame_rate)
            mimi.streaming_forever(1)
            gen.streaming_forever(1)
            # One frame of silence, so the first real frame is not also the
            # first CUDA allocation of every kernel in the graph.
            with torch.inference_mode():
                gen.step(mimi.encode(torch.zeros(1, 1, frame, device=device)))
        _send(
            "ready",
            sample_rate=int(mimi.sample_rate),
            frame_samples=frame,
            heads=heads,
            delay_seconds=float(checkpoint.stt_config.get("audio_delay_seconds", 0.5)),
        )
    except Exception as exc:  # noqa: BLE001 - process boundary must report upstream failures
        _send("error", error=f"Kyutai STT failed to load: {exc}")
        return

    first = True
    for line in sys.stdin:
        try:
            request = json.loads(line)
            operation = str(request.get("op") or "")
            if operation == "reset":
                # Inside inference mode: the streaming state was allocated
                # there, and PyTorch refuses an in-place update to an inference
                # tensor from outside it.
                with torch.inference_mode():
                    mimi.reset_streaming()
                    gen.reset_streaming()
                first = True
                _send("reset")
                continue
            if operation not in ("feed", "flush"):
                _send("error", error=f"unknown op {operation!r}")
                continue
            if operation == "flush":
                samples = np.zeros(frame, dtype=np.float32)
            else:
                raw = base64.b64decode(request.get("pcm") or "")
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32_768.0
                if samples.size != frame:
                    _send("error", error=f"expected {frame} samples, got {samples.size}")
                    continue
            index = int(request.get("vad_index", VAD_INDEX))
            with torch.inference_mode():
                chunk = torch.from_numpy(samples).to(device)[None, None, :]
                codes = mimi.encode(chunk)
                if first:
                    # The first step primes the depformer and returns nothing
                    # usable; upstream's own loop does the same.
                    gen.step(codes)
                    first = False
                found = gen.step_with_extra_heads(codes)
            if found is None:
                _send("text", text="", done=0.0)
                continue
            tokens, extra = found
            done = 0.0
            if extra and 0 <= index < len(extra):
                # Element 0 of the head's softmax is the probability of a pause
                # of that length. `prs[2][0] > 0.5` is Kyutai's own test.
                done = float(extra[index][0, 0, 0].item())
            token = int(tokens[0, 0].item())
            piece = ""
            if token not in (0, 3):
                piece = tokenizer.id_to_piece(token).replace("▁", " ")
            _send("text", text=piece, done=done)
        except Exception as exc:  # noqa: BLE001 - keep the host alive for the next request
            _send("error", error=str(exc))


if __name__ == "__main__":
    main()
